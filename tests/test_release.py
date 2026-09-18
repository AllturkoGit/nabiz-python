"""Sürüm etiketinin kendiliğinden bulunması (kardeş paketlerle ortak kural)."""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from nabiz import release  # noqa: E402

SHA = "0123456789ABCDEF0123456789abcdef01234567"
SHORT = "0123456789ab"
OTHER = "fedcba9876543210fedcba9876543210fedcba98"


class _Temp(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)

    def write(self, relative, content):
        path = Path(self.root, relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

        return path

    def detect(self, values=None, environ=None):
        return release.detect(root=self.root, values=values or {}, environ=environ or {})


class GitLayoutTest(_Temp):
    def test_dal_refi(self):
        self.write(".git/HEAD", "ref: refs/heads/main\n")
        self.write(".git/refs/heads/main", SHA + "\n")

        self.assertEqual((SHORT, ".git"), self.detect())

    def test_egik_cizgili_dal_adi(self):
        self.write(".git/HEAD", "ref: refs/heads/ozellik/yeni\n")
        self.write(".git/refs/heads/ozellik/yeni", SHA + "\n")

        self.assertEqual((SHORT, ".git"), self.detect())

    def test_yalnizca_packed_refs(self):
        self.write(".git/HEAD", "ref: refs/heads/main\n")
        self.write(
            ".git/packed-refs",
            "# pack-refs with: peeled fully-peeled sorted\n"
            f"{OTHER} refs/heads/baska\n"
            f"{SHA} refs/heads/main\n"
            f"^{OTHER}\n"
            f"{OTHER} refs/tags/v1.0.0\n",
        )

        self.assertEqual((SHORT, ".git"), self.detect())

    def test_packed_refs_te_de_yoksa_bos(self):
        self.write(".git/HEAD", "ref: refs/heads/main\n")
        self.write(".git/packed-refs", f"{OTHER} refs/heads/baska\n^{SHA}\n")

        self.assertEqual((None, None), self.detect())

    def test_ayrik_head(self):
        self.write(".git/HEAD", SHA + "\n")

        self.assertEqual((SHORT, ".git"), self.detect())

    def test_gitdir_dosyasi_goreli(self):
        self.write("gercek-git/HEAD", "ref: refs/heads/main\n")
        self.write("gercek-git/refs/heads/main", SHA)
        self.write("uygulama/.git", "gitdir: ../gercek-git\n")

        self.assertEqual((SHORT, ".git"), release.detect(
            root=os.path.join(self.root, "uygulama"), values={}, environ={}
        ))

    def test_gitdir_dosyasi_mutlak(self):
        self.write("gercek-git/HEAD", SHA)
        self.write(".git", f"gitdir: {os.path.join(self.root, 'gercek-git')}\n")

        self.assertEqual((SHORT, ".git"), self.detect())

    def test_bozuk_icerik(self):
        for head, ref in (
            ("ref: refs/heads/main", "bozuk-sha"),
            ("ref: refs/heads/main", SHA[:39]),
            ("ref: refs/heads/main", "g" * 40),
            ("anlamsiz", None),
            ("", None),
            (SHA[:12], None),
        ):
            shutil.rmtree(os.path.join(self.root, ".git"), ignore_errors=True)
            self.write(".git/HEAD", head)

            if ref is not None:
                self.write(".git/refs/heads/main", ref)

            self.assertEqual((None, None), self.detect(), (head, ref))

    def test_ref_refs_disina_cikamaz(self):
        # Kök dışındaki bir dosya sha gibi okunmasın.
        self.write("disari", SHA)
        self.write(".git/refs/heads/main", SHA)
        self.write(".git/HEAD_BASKA", SHA)

        for head in ("ref: ../disari", "ref: refs/heads/../../../disari", "ref: HEAD_BASKA",
                     "ref: refs/../HEAD_BASKA", "ref:"):
            self.write(".git/HEAD", head + "\n")

            self.assertEqual((None, None), self.detect(), head)

    def test_bozuk_gitdir_dosyasi(self):
        self.write(".git", "anlamsız içerik\n")
        self.assertEqual((None, None), self.detect())

        self.write(".git", "gitdir: yok/olan/yer\n")
        self.assertEqual((None, None), self.detect())

        self.write(".git", "gitdir:\n")
        self.assertEqual((None, None), self.detect())

    def test_git_yoksa_bos(self):
        self.assertEqual((None, None), self.detect())

    def test_utf8_olmayan_head_firlatmaz(self):
        Path(self.root, ".git").mkdir()
        Path(self.root, ".git", "HEAD").write_bytes(b"\xff\xfe\xe7")

        self.assertEqual((None, None), self.detect())

    def test_okuma_hatasi_firlatmaz(self):
        self.write(".git/HEAD", SHA)

        with mock.patch("builtins.open", side_effect=PermissionError("yasak")):
            self.assertEqual((None, None), self.detect())

        with mock.patch.object(release, "_gitdir", side_effect=RuntimeError("beklenmedik")):
            self.assertEqual((None, None), self.detect())


class PrecedenceTest(_Temp):
    def setUp(self):
        super().setUp()
        self.write(".git/HEAD", SHA)

    def test_nabiz_release_kazanir_kirpilir_64(self):
        self.assertEqual(
            ("v2.3-canli", "NABIZ_RELEASE"),
            self.detect(values={"NABIZ_RELEASE": "  v2.3-canli \n"}, environ={"GIT_COMMIT": OTHER}),
        )
        self.assertEqual("x" * 64, self.detect(values={"NABIZ_RELEASE": "x" * 80})[0])
        # Olduğu gibi: sha görünümlü değer kısaltılmaz, küçültülmez.
        self.assertEqual(SHA, self.detect(values={"NABIZ_RELEASE": SHA})[0])

    def test_bos_nabiz_release_atlanir(self):
        self.assertEqual((SHORT, ".git"), self.detect(values={"NABIZ_RELEASE": "   "}))

    def test_ortam_degiskeni_listesi_ortak_sartnameyle_ayni(self):
        # Node ve Laravel aynı listeyi aynı sırayla okur.
        self.assertEqual(
            ("GIT_COMMIT", "GIT_SHA", "COMMIT_SHA", "SOURCE_VERSION", "VERCEL_GIT_COMMIT_SHA",
             "RENDER_GIT_COMMIT", "HEROKU_SLUG_COMMIT", "CI_COMMIT_SHA"),
            release.RELEASE_ENV_VARS,
        )

    def test_ortam_degiskeni_sirasi(self):
        environ = {name: f"{i:x}" * 40 for i, name in enumerate(release.RELEASE_ENV_VARS, start=1)}

        for name in release.RELEASE_ENV_VARS:
            value, source = self.detect(environ=environ)
            self.assertEqual(name, source)
            self.assertEqual(environ[name][:12], value)
            del environ[name]

        self.assertEqual((SHORT, ".git"), self.detect(environ=environ))

    def test_ortam_degiskeni_hex_ise_kisaltilir_degilse_kirpilir(self):
        self.assertEqual(("abcdef1", "GIT_SHA"), self.detect(environ={"GIT_SHA": "ABCDEF1"}))
        self.assertEqual((SHORT, "GIT_SHA"), self.detect(environ={"GIT_SHA": SHA}))
        self.assertEqual(("sürüm-42", "COMMIT_SHA"), self.detect(environ={"COMMIT_SHA": " sürüm-42 "}))
        self.assertEqual("y" * 64, self.detect(environ={"COMMIT_SHA": "y" * 100})[0])
        # 6 hane hex eşleşmez: olduğu gibi.
        self.assertEqual(("ABCDEF", "COMMIT_SHA"), self.detect(environ={"COMMIT_SHA": "ABCDEF"}))
        # Boş değer atlanır.
        self.assertEqual(("abcdef1", "GIT_SHA"), self.detect(environ={"GIT_COMMIT": "  ", "GIT_SHA": "abcdef1"}))

    def test_varsayilan_kok_calisma_dizini(self):
        previous = os.getcwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, previous)

        self.assertEqual((SHORT, ".git"), release.detect(values={}, environ={}))


class InitTest(_Temp):
    def setUp(self):
        super().setUp()
        import nabiz
        from nabiz import env as env_module

        self.write(".git/HEAD", SHA)
        self.previous = os.getcwd()
        self.saved = {k: os.environ.pop(k) for k in list(os.environ)
                      if k.startswith("NABIZ_") or k in release.RELEASE_ENV_VARS}
        self.instance = nabiz._instance
        os.chdir(self.root)
        env_module.forget()

        def restore():
            os.chdir(self.previous)
            os.environ.update(self.saved)
            env_module.forget()
            nabiz._instance = self.instance

        self.addCleanup(restore)

    def test_init_git_etiketini_kullanir(self):
        import nabiz

        self.assertEqual(SHORT, nabiz.init().release)
        self.assertEqual(SHORT, nabiz.from_environment()["release"])

    def test_acik_release_kazanir_git_okunmaz(self):
        import nabiz

        with mock.patch.object(release, "git_sha", return_value="okunmamali") as spy:
            self.assertEqual("elle", nabiz.init(release="elle").release)

        self.assertEqual(0, spy.call_count)

    def test_ortam_git_i_yener(self):
        import nabiz

        with mock.patch.dict(os.environ, {"HEROKU_SLUG_COMMIT": OTHER}):
            self.assertEqual(OTHER[:12], nabiz.init().release)


if __name__ == "__main__":
    unittest.main()
