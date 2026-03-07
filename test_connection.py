from app import create_app
from app.extensions import db
from sqlalchemy import inspect

# Importer les modèles pour que SQLAlchemy les connaisse
from app.models.user import User

app = create_app()

with app.app_context():
    # Crée toutes les tables
    db.create_all()

    # Lister les tables
    inspector = inspect(db.engine)
    tables = inspector.get_table_names()
    print("Tables PostgreSQL :", tables)

    # Vérifier MongoDB
    print("MongoDB connecté à :", app.mongo.name)