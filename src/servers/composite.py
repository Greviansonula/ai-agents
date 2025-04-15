# COMPOSITE MCP SERVER

from fastmcp import FastMCP
import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from servers.postgres_mcp import postgres_mcp 
from servers.couch_mcp import couchdb_mcp 
from servers.aws_mcp import aws_mcp 


mcp = FastMCP("Composite")

# Mount sub-apps with prefixes
mcp.mount("postgres", postgres_mcp) 
mcp.mount("couchdb", couchdb_mcp) 
mcp.mount('aws', aws_mcp)

@mcp.tool()
def ping(): 
    return "Composite OK"


if __name__ == "__main__":
    mcp.run()