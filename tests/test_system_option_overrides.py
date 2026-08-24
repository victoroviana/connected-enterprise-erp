import pytest
from flask import Flask

from models import db, SystemOptionOverride
from utils.systems import get_system_option, iter_system_options


@pytest.fixture()
def app(tmp_path):
    app = Flask(__name__)
    db_path = tmp_path / "test_overrides.db"
    app.config.update(
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{db_path}",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)
    with app.app_context():
        db.create_all()
    yield app
    with app.app_context():
        db.drop_all()


def test_get_system_option_uses_override_description_and_image(app):
    with app.app_context():
        db.session.add(SystemOptionOverride(
            key='rhid',
            description='Descricao personalizada',
            image_path='static/system_options/custom.png',
        ))
        db.session.commit()

        option = get_system_option('rhid')
        assert option.description == 'Descricao personalizada'
        assert option.image == 'static/system_options/custom.png'


def test_iter_system_options_reflects_overrides(app):
    with app.app_context():
        db.session.add(SystemOptionOverride(
            key='sollus_access',
            description='Override Sollus',
        ))
        db.session.commit()

        options = {opt.key: opt for opt in iter_system_options()}
        assert options['sollus_access'].description == 'Override Sollus'