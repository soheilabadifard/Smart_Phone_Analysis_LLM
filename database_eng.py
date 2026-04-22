import os

from sqlalchemy import URL
from sqlalchemy import create_engine


def create_table(username, password, db_name, host="localhost", port=3306):
    driver = os.getenv("DB_DRIVER", "pymysql")
    url_object = URL.create(
        f"mysql+{driver}",
        username=username,
        password=password,
        host=host,
        port=port,
        database=db_name
    )
    return create_engine(url_object)


def create_schema(username, password, host="localhost", port=3306):
    driver = os.getenv("DB_DRIVER", "pymysql")
    url_object = URL.create(f'mysql+{driver}',
                            username=username,
                            password=password,
                            host=host,
                            port=port)
    return create_engine(url_object)
