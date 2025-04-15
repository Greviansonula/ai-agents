# MCP Client for Composite Agent
import asyncio
from dataclasses import dataclass, field
from typing import Union, cast, Dict, Any, List
from jsonschema import validate, ValidationError
from tenacity import retry, wait_exponential, stop_after_attempt
import anthropic
from anthropic.types import MessageParam, TextBlock, ToolUnionParam, ToolUseBlock
from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from loguru import logger
import os
import datetime

# Configure loguru for detailed tracing to file
log_directory = "logs"
os.makedirs(log_directory, exist_ok=True)
timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
log_file = os.path.join(log_directory, f"chat_trace_{timestamp}.log")

# Configure loguru logger
logger.remove()  # Remove default handler
logger.add(log_file, 
           level="TRACE", 
           format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
           rotation="20 MB")
logger.add(lambda msg: print(msg, flush=True), level="INFO", format="{message}")

logger.info(f"Starting new chat session. Log file: {log_file}")


load_dotenv()

anthropic_client = anthropic.AsyncAnthropic()
MAX_TOKENS = 100000  # Conservative limit for Claude's 200k context window
RETRY_ATTEMPTS = 3

# Create server parameters for stdio connection
server_params = StdioServerParameters(
    command="python",  # Executable
    args=["../servers/composite.py"],  # Optional command line arguments
    env=None,  # Optional environment variables
)

@dataclass
class Chat:
    messages: list[MessageParam] = field(default_factory=list)
    system_prompt: str = """You are a Super Technical Support Assistant you help trouble shoot user request/issues. Your role is to provide users with accurate, concise, and user-friendly assistance based on issues reported. Maintain a professional and empathetic tone, prioritize clarity, and avoid unnecessary technical jargon. Break down complex issues into manageable steps, and if a problem requires further assistance beyond your capabilities, guide the user on how to seek additional help. Ensure that all information provided is up-to-date and relevant to the user's context.

    System workflow:
    1. Messages are send from SQS to the appropriate lambda function.
    2. The lambda function processes the message and returns a response.
    3. If the lambda function cannot process the message, it returns an error message.
    """
    available_tools: list[ToolUnionParam] = field(default_factory=list)

    async def initialize_tools(self, session: ClientSession) -> None:
        """Fetch and cache available tools with schemas"""
        print("📋 Initializing available tools...")
        response = await session.list_tools()
        self.available_tools = [
            {
                "name": tool.name,
                "description": tool.description or "",
                "input_schema": tool.inputSchema,
            }
            for tool in response.tools
        ]
        logger.info(f"Available tools initialized: {[t['name'] for t in self.available_tools]}")
        print(f"✅ Initialized {len(self.available_tools)} tools")

    @retry(wait=wait_exponential(multiplier=1, min=1, max=10), 
           stop=stop_after_attempt(RETRY_ATTEMPTS))
    async def claude_request(self, **kwargs) -> anthropic.types.Message:
        """Wrapper with retry logic for Claude API calls"""
        print(f"🤖 Sending request to Claude API...")
        try:
            response = await anthropic_client.messages.create(**kwargs)
            print(f"✅ Received response from Claude API")
            return response
        except anthropic.APIError as e:
            print(f"❌ Claude API error: {str(e)}")
            logger.error(f"Claude API error: {str(e)}")
            raise

    async def _truncate_messages(self):
        """Maintain conversation history within token limits"""
        print("📏 Checking conversation token count...")
        token_count = await anthropic_client.messages.count_tokens(
            model="claude-3-7-sonnet-20250219",
            messages=self.messages
        )
        print(f"📊 Current token count: {token_count.input_tokens}/{MAX_TOKENS}")
        
        while token_count.input_tokens > MAX_TOKENS:
            if len(self.messages) > 1:
                removed = self.messages.pop(1)  # Preserve system prompt
                print(f"✂️ Truncated message: {str(removed)[:50]}...")
                logger.warning(f"Truncated message: {str(removed)[:50]}...")
                # Recalculate tokens after removing a message
                token_count = await anthropic_client.messages.count_tokens(
                    model="claude-3-7-sonnet-20250219",
                    messages=self.messages
                )
                print(f"📊 Updated token count: {token_count.input_tokens}/{MAX_TOKENS}")
            else:
                print("⚠️ Cannot truncate further - only system message remains")
                break


    async def process_tool_use(self, session: ClientSession, tool_use: ToolUseBlock) -> dict:
        """Execute tool with validation and error handling"""
        print(f"🛠️ Executing tool: {tool_use.name} (ID: {tool_use.id})")
        print(f"📥 Tool input: {tool_use.input}")
        
        tool = next((t for t in self.available_tools if t["name"] == tool_use.name), None)
        
        if not tool:
            print(f"❌ Tool '{tool_use.name}' not found")
            return {
                "tool_use_id": tool_use.id,
                "content": f"Tool '{tool_use.name}' not found"
            }
        
        try:
            # Validate against tool schema
            print(f"🔍 Validating input against schema for {tool_use.name}...")
            validate(instance=tool_use.input, schema=tool["input_schema"])
            print(f"✅ Input validation successful")
            
            # Execute tool
            print(f"⚙️ Executing {tool_use.name}...")
            result = await session.call_tool(tool_use.name, cast(dict, tool_use.input))
            tool_result = {
                "tool_use_id": tool_use.id,
                "content": result.content[0].text if result.content else ""
            }
            print(f"✅ Tool execution complete")
            print(f"📤 Tool result: {tool_result['content'][:100]}..." if len(tool_result['content']) > 100 else f"📤 Tool result: {tool_result['content']}")
            return tool_result
            
        except ValidationError as ve:
            error_msg = f"Validation error: {str(ve)}"
            print(f"❌ {error_msg}")
            logger.error(f"Validation error for {tool_use.name}: {str(ve)}")
            return {"tool_use_id": tool_use.id, "content": error_msg}
        except Exception as e:
            error_msg = f"Execution error: {str(e)}"
            print(f"❌ {error_msg}")
            logger.error(f"Tool execution error for {tool_use.name}: {str(e)}")
            return {"tool_use_id": tool_use.id, "content": error_msg}

    async def process_query(self, session: ClientSession, query: str) -> None:
        """Enhanced query processing with full tool handling"""
        print("\n" + "="*50)
        print(f"📝 Processing query: {query}")
        self.messages.append({"role": "user", "content": query})
        
        iteration = 0
        while True:
            if iteration > 0:
                print(f"\n🔄 Iteration {iteration+1} - Processing tool results...")
            iteration += 1
            
            try:
                # Get Claude response with retry
                print(f"🧠 Thinking...")
                res = await self.claude_request(
                    model="claude-3-7-sonnet-20250219",
                    system=self.system_prompt,
                    max_tokens=8000,
                    messages=self.messages,
                    tools=self.available_tools,
                )
            except Exception as e:
                error_msg = f"System error: Failed to get response ({str(e)})"
                self.messages.append({
                    "role": "assistant", 
                    "content": error_msg
                })
                print(f"❌ {error_msg}")
                break

            # Process response content
            tool_uses = [c for c in res.content if isinstance(c, ToolUseBlock)]
            text_blocks = [c for c in res.content if isinstance(c, TextBlock)]

            print(f"📊 Response breakdown: {len(text_blocks)} text blocks, {len(tool_uses)} tool calls")

            # Print immediate text response
            if text_blocks:
                print("\n🗣️ Claude's response:")
                for block in text_blocks:
                    print(block.text)

            if not tool_uses:
                print("✅ Query complete - no tools needed")
                # Add full response to messages for history
                self.messages.append({
                    "role": "assistant",
                    "content": res.content
                })
                break  # Exit loop if no tools needed
            else:
                print(f"\n🛠️ Tools requested: {', '.join([t.name for t in tool_uses])}")

            # Process all tool uses in parallel
            print("⚙️ Executing tools in parallel...")
            tool_results = await asyncio.gather(
                *[self.process_tool_use(session, tool_use) for tool_use in tool_uses]
            )

            # Update conversation history
            self.messages.append({
                "role": "assistant",
                "content": res.content
            })
            
            # Construct tool_results in the correct format
            tool_results_content = [{
                "type": "tool_result",
                "tool_use_id": result["tool_use_id"],
                "content": result["content"]
            } for result in tool_results]
            
            print("\n📤 Sending tool results back to Claude...")
            self.messages.append({
                "role": "user",
                "content": tool_results_content
            })

            # Maintain token window
            await self._truncate_messages()

        print("="*50 + "\n")

    async def chat_loop(self, session: ClientSession):
        """Main chat interface with session management"""
        print("\n🚀 Starting chat interface")
        await self.initialize_tools(session)
        print("\n📋 Available tools:")
        for tool in self.available_tools:
            #print(f"  • {tool['name']}: {tool['description']}")
            print(f"  • {tool['name']} ")

        while True:
            try:
                query = input("\nQuery: ").strip()
                if query.lower() in ('exit', 'quit'):
                    print("👋 Exiting chat loop")
                    break
                await self.process_query(session, query)
            except (KeyboardInterrupt, EOFError):
                print("\n👋 Interrupted. Exiting chat loop")
                break
            except Exception as e:
                logger.error(f"Chat error: {str(e)}")
                print(f"❌ Chat error: {str(e)}")
                print("Sorry, an error occurred. Please try again.")

    async def run(self):
        """Main entry point with connection management"""
        print("🔌 Establishing connection to server...")
        async with stdio_client(server_params) as (read, write):
            print("✅ Connection established")
            async with ClientSession(read, write) as session:
                print("🔄 Initializing session...")
                await session.initialize()
                print("✅ Session initialized")
                await self.chat_loop(session)
                print("👋 Session ended")
