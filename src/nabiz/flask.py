"""Flask entegrasyonu: yavaş istek, 5xx ve yakalanmamış istisna ölçümü.

Kullanım::

    from flask import Flask
    from nabiz.flask import NabizFlask

    app = Flask(__name__)
    NabizFlask(app)

Flask bu modülün **içinde** import edilir; paketin kendisi Flask'a bağımlı
değildir ve Flask kurulu olmayan bir projede ``import nabiz`` çalışmaya devam
eder.

Kancalar ``teardown_request`` ve ``after_request`` üzerine kurulur; ``blinker``
sinyalleri kullanılmaz — sinyal bağımlılığı Flask sürümüne göre değişiyor ve
bu paketin bağımlılık politikası sıfır.
"""

import time

from . import hook_process, reporter, scrubber

#: İstek başlangıcını ``flask.g`` üzerinde taşıyan alan adı.
_STARTED_AT = "_nabiz_started_at"


class NabizFlask:
    """Flask eklentisi.

    :param app: Uygulama. Verilmezse sonradan ``init_app`` çağrılır.
    :param hook_process_errors: Yakalanmamış istisna kancalarını ve canlılık
        zamanlayıcısını da kurar. Varsayılan açık: kurulum reçetesinin tek
        adımda bitmesi, canlılığın ayrıca hatırlanması gereken bir çağrı
        olmamasından daha güvenli.
    """

    def __init__(self, app=None, hook_process_errors=True):
        self.hook_process_errors = hook_process_errors

        if app is not None:
            self.init_app(app)

    def init_app(self, app):
        from flask import g, request

        current = reporter()

        @app.before_request
        def _nabiz_before():
            setattr(g, _STARTED_AT, time.perf_counter())

        @app.after_request
        def _nabiz_after(response):
            try:
                started = getattr(g, _STARTED_AT, None)

                if started is not None:
                    current.record_request(
                        route=route_pattern(request),
                        method=request.method,
                        status=response.status_code,
                        duration_ms=(time.perf_counter() - started) * 1000,
                    )
            except Exception:  # noqa: BLE001
                # İzleme kodu isteği bozmaz.
                pass

            return response

        @app.teardown_request
        def _nabiz_teardown(error=None):
            # Hata **yutulmaz**: teardown yalnızca bilgilendirilir, Flask'ın
            # kendi hata sayfası ve handler zinciri olduğu gibi çalışır.
            if error is None:
                return

            try:
                current.record_exception(
                    error,
                    route=route_pattern(request),
                    method=request.method,
                )
            except Exception:  # noqa: BLE001
                pass

        if self.hook_process_errors:
            hook_process()

        return app


def route_pattern(request):
    """Flask'ın eşleşen rota deseni (``/urun/<id>``), gerçek yol değil.

    Hem gruplama çalışır — aynı rota tek parmak izinde toplanır — hem de yolda
    kişisel veri taşınmaz. Desen yoksa (404) yola düşülür ve query string
    atılır (M3).
    """
    try:
        rule = request.url_rule.rule if request.url_rule is not None else None
    except Exception:  # noqa: BLE001
        rule = None

    return scrubber.path(rule or request.path) or "/"
