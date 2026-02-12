import os

import pymysql


DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "chin1987")
DB_NAME = os.getenv("DB_NAME", "flora_db")


try:
    connection = pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
    )
    with connection.cursor() as cursor:
        cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{DB_NAME}`")
        print(f"Database {DB_NAME} created successfully")
except Exception as exc:
    print(f"Error creating database: {exc}")
finally:
    if "connection" in locals() and connection.open:
        connection.close()
