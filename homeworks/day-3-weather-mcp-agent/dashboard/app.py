from __future__ import annotations

import os

from flask import Flask, jsonify, render_template

from lakebase import DashboardRepository, LakebaseError


def create_app(repository: DashboardRepository | None = None) -> Flask:
    app = Flask(__name__)
    repo = repository or DashboardRepository()

    @app.get("/healthz")
    def healthz():
        return jsonify({"status": "ok", "service": "day3-weather-dashboard"})

    @app.get("/api/activity")
    def activity():
        try:
            return jsonify(repo.overview())
        except LakebaseError as error:
            return jsonify({"error": str(error)}), 503

    @app.get("/")
    def home():
        try:
            return render_template("index.html", data=repo.overview(), error=None)
        except LakebaseError as error:
            return render_template("index.html", data={"overview": {"total_calls": 0, "failures": 0, "last_hour_calls": 0}, "activity": []}, error=str(error))

    return app


app = create_app() if os.getenv("DASHBOARD_SKIP_APP_INIT") != "1" else Flask(__name__)
