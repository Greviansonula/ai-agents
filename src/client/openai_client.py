# support_agent.py
from dataclasses import dataclass, field
from typing import Union, cast, Dict, Any, List
import asyncio
import json
import os
import datetime

import openai
from jsonschema import validate, ValidationError
from tenacity import retry, wait_exponential, stop_after_attempt
from dotenv import load_dotenv
from loguru import logger

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# Configure logging
log_directory = "logs"
os.makedirs(log_directory, exist_ok=True)
timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
log_file = os.path.join(log_directory, f"chat_trace_{timestamp}.log")

logger.remove()
logger.add(log_file, 
           level="TRACE", 
           format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
           rotation="20 MB")
logger.add(lambda msg: print(msg, flush=True), level="INFO", format="{message}")

load_dotenv()

# Constants
MAX_TOKENS = 100000
RETRY_ATTEMPTS = 3
MODEL = "gpt-4o"

# Server parameters
server_params = StdioServerParameters(
    command="python",
    args=["servers/composite.py"],
    env=None,
)

@dataclass
class Chat:
    messages: list[Dict[str, Any]] = field(default_factory=list)
    system_prompt: str = """You are a Super Technical Support Assistant you help trouble shoot user request/issues. 
    Your role is to provide users with accurate, concise, and user-friendly assistance based on issues reported. 
    Maintain a professional and empathetic tone, prioritize clarity, and avoid unnecessary technical jargon. 
    Break down complex issues into manageable steps, and if a problem requires further assistance beyond your capabilities, guide the user on how to seek additional help. Ensure that all information provided is up-to-date and relevant to the user's context.

    System workflow:
    1. Messages are send from SQS to the appropriate lambda function.
    2. The lambda function processes the message and returns a response.
    3. If the lambda function cannot process the message, it returns an error message.

    The default aws region is us-east-1
    """
    available_tools: list[Dict[str, Any]] = field(default_factory=list)
    
    def __post_init__(self):
        # Initialize OpenAI client
        self.client = openai.AsyncOpenAI()
        logger.info("Chat instance initialized")
    
    async def initialize_tools(self, session: ClientSession) -> None:
        """Fetch and cache available tools with schemas"""
        print("📋 Initializing available tools...")
        response = await session.list_tools()
        self.available_tools = [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description or "",
                    "parameters": tool.inputSchema,
                }
            }
            for tool in response.tools
        ]
        logger.info(f"Available tools initialized: {[t['function']['name'] for t in self.available_tools]}")
        print(f"✅ Initialized {len(self.available_tools)} tools")

    @retry(wait=wait_exponential(multiplier=1, min=1, max=10), 
           stop=stop_after_attempt(RETRY_ATTEMPTS))
    async def openai_request(self, **kwargs) -> Any:
        """Make OpenAI API request with retry"""
        print(f"🤖 Sending request to OpenAI API...")
        try:
            response = await self.client.chat.completions.create(**kwargs)
            print(f"✅ Received response from OpenAI API")
            return response
        except openai.OpenAIError as e:
            print(f"❌ OpenAI API error: {str(e)}")
            logger.error(f"OpenAI API error: {str(e)}")
            raise

    async def _truncate_messages(self):
        """Maintain conversation history within token limits"""
        print("📏 Checking conversation token count...")
        # Approximate token count based on characters
        char_count = sum(len(str(m)) for m in self.messages)
        estimated_tokens = char_count // 4
        
        print(f"📊 Estimated token count: {estimated_tokens}/{MAX_TOKENS}")
        
        while estimated_tokens > MAX_TOKENS:
            if len(self.messages) > 1:
                removed = self.messages.pop(1)
                print(f"✂️ Truncated message: {str(removed)[:50]}...")
                logger.warning(f"Truncated message: {str(removed)[:50]}...")
                
                char_count = sum(len(str(m)) for m in self.messages)
                estimated_tokens = char_count // 4
                print(f"📊 Updated estimated token count: {estimated_tokens}/{MAX_TOKENS}")
            else:
                print("⚠️ Cannot truncate further - only system message remains")
                break

    async def process_tool_call(self, session: ClientSession, tool_call) -> dict:
        """Execute tool with validation and error handling"""
        tool_name = tool_call.function.name
        print(f"🛠️ Executing tool: {tool_name} (ID: {tool_call.id})")
        print(f"📥 Tool input: {tool_call.function.arguments}")
        
        tool = next((t for t in self.available_tools if t["function"]["name"] == tool_name), None)
        
        if not tool:
            print(f"❌ Tool '{tool_name}' not found")
            return {
                "tool_call_id": tool_call.id,
                "output": f"Tool '{tool_name}' not found"
            }
        
        try:
            # Parse JSON arguments
            tool_args = json.loads(tool_call.function.arguments)
            
            # Validate against tool schema
            print(f"🔍 Validating input against schema for {tool_name}...")
            validate(instance=tool_args, schema=tool["function"]["parameters"])
            print(f"✅ Input validation successful")
            
            # Execute tool
            print(f"⚙️ Executing {tool_name}...")
            result = await session.call_tool(tool_name, cast(dict, tool_args))
            tool_result = {
                "tool_call_id": tool_call.id,
                "output": result.content[0].text if result.content else ""
            }
            print(f"✅ Tool execution complete")
            print(f"📤 Tool result: {tool_result['output'][:100]}..." if len(tool_result['output']) > 100 else f"📤 Tool result: {tool_result['output']}")
            return tool_result
            
        except ValidationError as ve:
            error_msg = f"Validation error: {str(ve)}"
            print(f"❌ {error_msg}")
            logger.error(f"Validation error for {tool_name}: {str(ve)}")
            return {"tool_call_id": tool_call.id, "output": error_msg}
        except Exception as e:
            error_msg = f"Execution error: {str(e)}"
            print(f"❌ {error_msg}")
            logger.error(f"Tool execution error for {tool_name}: {str(e)}")
            return {"tool_call_id": tool_call.id, "output": error_msg}

    async def process_query(self, session: ClientSession, query: str) -> None:
        """Process user query with tool support"""
        print("\n" + "="*50)
        print(f"📝 Processing query: {query}")
        self.messages.append({"role": "user", "content": query})
        
        iteration = 0
        while True:
            if iteration > 0:
                print(f"\n🔄 Iteration {iteration+1} - Processing tool results...")
            iteration += 1
            
            try:
                # Get OpenAI response
                print(f"🧠 Thinking...")
                res = await self.openai_request(
                    model=MODEL,
                    messages=[{"role": "system", "content": self.system_prompt}] + self.messages,
                    max_tokens=4096,
                    tools=self.available_tools if self.available_tools else None,
                    tool_choice="auto",
                )
                
                assistant_message = res.choices[0].message
            except Exception as e:
                error_msg = f"System error: Failed to get response ({str(e)})"
                self.messages.append({
                    "role": "assistant", 
                    "content": error_msg
                })
                print(f"❌ {error_msg}")
                break

            # Store assistant response in history
            assistant_message_dict = {
                "role": "assistant",
                "content": assistant_message.content
            }
            
            if assistant_message.tool_calls:
                assistant_message_dict["tool_calls"] = assistant_message.tool_calls
            
            self.messages.append(assistant_message_dict)

            # Print text response
            if assistant_message.content:
                print("\n🗣️ AI response:")
                print(assistant_message.content)

            # Process tool calls if any
            if not assistant_message.tool_calls:
                print("✅ Query complete - no tools needed")
                break
            else:
                tool_calls = assistant_message.tool_calls
                print(f"\n🛠️ Tools requested: {', '.join([call.function.name for call in tool_calls])}")

                # Process tools in parallel
                print("⚙️ Executing tools in parallel...")
                tool_results = await asyncio.gather(
                    *[self.process_tool_call(session, tool_call) for tool_call in tool_calls]
                )
                
                # Add tool results to messages
                for result in tool_results:
                    self.messages.append({
                        "role": "tool",
                        "tool_call_id": result["tool_call_id"],
                        "content": result["output"]
                    })

                print("\n📤 Sending tool results back to OpenAI...")

            # Maintain token window
            await self._truncate_messages()

        print("="*50 + "\n")

    async def chat_loop(self, session: ClientSession):
        """Main chat interface"""
        print("\n🚀 Starting chat interface")
        await self.initialize_tools(session)
        print("\n📋 Available tools:")
        for tool in self.available_tools:
            print(f"  • {tool['function']['name']}")

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
        """Main entry point"""
        print("🔌 Establishing connection to server...")
        async with stdio_client(server_params) as (read, write):
            print("✅ Connection established")
            async with ClientSession(read, write) as session:
                print("🔄 Initializing session...")
                await session.initialize()
                print("✅ Session initialized")
                await self.chat_loop(session)
                print("👋 Session ended")

if __name__ == "__main__":
    print("🚀 Starting chat agent")
    chat = Chat()
    asyncio.run(chat.run())