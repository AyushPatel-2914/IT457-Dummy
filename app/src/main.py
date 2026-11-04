"""App factory. SERVICE selects what this process serves:

    monolith         all endpoints in one process (S0, S1)
    catalogue        /, /movies, /movies/<id>  (S2)
    recommendations  /recommendations/<user>   (S2)
    auth             /login                    (S2)
"""
import os
import socket

from flask import Flask, jsonify

from . import auth, catalogue, db, recommendations

BLUEPRINTS = {
    "monolith": [catalogue.bp, recommendations.bp, auth.bp],
    "catalogue": [catalogue.bp],
    "recommendations": [recommendations.bp],
    "auth": [auth.bp],
}


def create_app(service=None):
    service = service or os.environ.get("SERVICE", "monolith")
    if service not in BLUEPRINTS:
        raise ValueError(f"unknown SERVICE {service!r}")
    instance = os.environ.get("INSTANCE_ID") or socket.gethostname()

    app = Flask(__name__)
    app.json.sort_keys = False
    db.init()
    for bp in BLUEPRINTS[service]:
        app.register_blueprint(bp)

    @app.get("/health")
    def health():
        try:
            db.ping()
        except Exception as exc:
            return jsonify(status="db-error", service=service, instance=instance, detail=str(exc)), 503
        return jsonify(status="ok", service=service, instance=instance)

    @app.after_request
    def tag_response(resp):
        # Lets the load generator record which instance and service answered each request.
        resp.headers["X-Served-By"] = f"{instance}/{service}"
        return resp

    return app


if __name__ == "__main__":
    # Development server for running without Docker (e.g. on Windows). Use gunicorn in containers.
    create_app().run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), threaded=True)
