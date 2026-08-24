"""Entry-point for running the platform locally."""
from gevent import monkey
monkey.patch_all()

from platform_app import create_app

app = create_app()

if __name__ == "__main__":
    from gevent.pywsgi import WSGIServer as _WSGIServer

    http_server = _WSGIServer(("0.0.0.0", 6002), app, backlog=512)
    http_server.serve_forever()

