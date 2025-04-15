# POSTGRES MCP SERVER

import os
import psycopg2
import couchdb

from loguru import logger
from fastmcp import FastMCP
from dotenv import load_dotenv

load_dotenv()

# PostgreSQL connection details
PG_USER = os.getenv("PG_USER")
PG_PASSWORD = os.getenv("PG_PASSWORD")
PG_DB = os.getenv("PG_DB")
DB_HOST = os.getenv("DB_HOST")

postgres_url = f"postgresql://{PG_USER}:{PG_PASSWORD}@{DB_HOST}/{PG_DB}"

# Create an MCP server
postgres_mcp = FastMCP("Data Support Agent")

@postgres_mcp.tool("query_postgres")
def query_pg(sql: str) -> str:
    """Execute SQL queries safely"""
    logger.info(f"Executing SQL query: {sql}")
    conn = psycopg2.connect(
        user=PG_USER,
        password=PG_PASSWORD,
        host=DB_HOST,
        database=PG_DB
    )
    try:
        cursor = conn.cursor()
        cursor.execute(sql)
        
        # Check if the query returns results
        if cursor.description:
            result = cursor.fetchall()
            return "\n".join(str(row) for row in result)
        else:
            conn.commit()
            return f"Query executed successfully. Rows affected: {cursor.rowcount}"
    except Exception as e:
        return f"Error: {str(e)}"
    finally:
        conn.close()


@postgres_mcp.prompt()
def mobilization_prompt(previous_membership: str, current_membership: str) -> str:
    return f"Please review this location mobilized from {previous_membership} to {current_membership}"
