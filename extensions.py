from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from flask_wtf import CSRFProtect
from flask_mail import Mail
from concurrent.futures import ThreadPoolExecutor

"""Central extensions shared by all modules."""


# SQLAlchemy instance used by both proposals and chamados modules
# Import this ``db`` everywhere instead of instantiating new ones.
db: SQLAlchemy = SQLAlchemy()

# Global thread pool executor for background tasks
executor: ThreadPoolExecutor = ThreadPoolExecutor(max_workers=5)

# Additional Flask extensions reused by both projects
migrate: Migrate = Migrate()
login_manager: LoginManager = LoginManager()
csrf: CSRFProtect = CSRFProtect()
mail: Mail = Mail()
