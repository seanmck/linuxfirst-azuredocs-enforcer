from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from webui.models import Base
import os

DB_URL = os.environ.get("DATABASE_URL", "postgresql://azuredocs_user:azuredocs_pass@localhost:5432/azuredocs?sslmode=disable")
engine = create_engine(DB_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    Base.metadata.create_all(bind=engine)
