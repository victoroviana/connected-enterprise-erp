from flask import Flask
from sqlalchemy import inspect, text

from models import db
from utils.schema import LEGACY_PROPOSAL_COLUMNS, ensure_proposal_email_columns


def test_ensure_proposal_email_columns_adds_missing_columns():
    app = Flask(__name__)
    app.config.update(
        SQLALCHEMY_DATABASE_URI="sqlite://",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )

    db.init_app(app)

    with app.app_context():
        engine = db.engine
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    CREATE TABLE proposals (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        company VARCHAR(255)
                    )
                    """
                )
            )

        ensure_proposal_email_columns()

        inspector = inspect(engine)
        column_names = {column["name"] for column in inspector.get_columns("proposals")}

        assert set(LEGACY_PROPOSAL_COLUMNS).issubset(column_names)
