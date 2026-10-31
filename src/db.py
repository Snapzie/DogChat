import logging
import os
import time
import pyodbc
from dotenv import load_dotenv
from sqlalchemy import create_engine, event
from sqlalchemy.engine import URL
from sqlalchemy.pool import NullPool

load_dotenv()
pyodbc.pooling = False
connection_variable = os.environ.get("DATABASE_CONNECTION_ENV", "DATABASE_AGENT")

connection_url = URL.create(
    "mssql+pyodbc",
    query={"odbc_connect": os.environ[connection_variable]},
)

engine = create_engine(connection_url, poolclass=NullPool)


@event.listens_for(engine, "do_connect")
def connect_with_retry(dialect, connection_record, connection_args, connection_options):
    for attempt in range(3):
        try:
            return dialect.loaded_dbapi.connect(*connection_args, **connection_options)
        except pyodbc.OperationalError as error:
            if attempt == 2 or not error.args or error.args[0] not in {"HYT00", "HYT01", "08001", "08S01"}:
                raise
            logging.getLogger(__name__).warning("Database connection unavailable; retrying (attempt %s/3).", attempt + 2)
            time.sleep(2)
