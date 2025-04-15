# AWS MCP SERVER

from fastmcp import FastMCP
import boto3
import json
from datetime import datetime, timezone

# Create a CloudWatch Logs client
client = boto3.client('logs')

# Initialize FastMCP server
aws_mcp = FastMCP("AWS Tools")

# Create Boto3 clients
lambda_client = boto3.client('lambda', region_name='us-east-1')
cloudwatch_client = boto3.client('cloudwatch', region_name='us-east-1')

# Lambda tools
@aws_mcp.tool()
def list_lambda_functions(region: str) -> str:
    """List all Lambda functions in the specified region"""
    response = lambda_client.list_functions()
    functions = [f['FunctionName'] for f in response['Functions']]
    return f"Lambda functions in {region}: {functions}"

@aws_mcp.tool()
def invoke_lambda_function(function_name: str, payload: str) -> str:
    """Invoke a Lambda function with the given payload"""
    response = lambda_client.invoke(FunctionName=function_name, Payload=payload)
    return f"Invocation result: {response['Payload'].read().decode()}"

# CloudWatch tools
@aws_mcp.tool()
def get_cloudwatch_logs(
    log_group_name: str,
    start_time: int = None,
    end_time: int = None,
    hours_back: int = None,
    filter_pattern: str = None,
    log_stream_names: list = None
) -> str:
    """
    Get log events from the specified CloudWatch log group with optional time filters and patterns.
    
    :param log_group_name: Name of the CloudWatch log group.
    :param start_time: Start time in milliseconds (alternative to hours_back).
    :param end_time: End time in milliseconds (defaults to now if not provided).
    :param hours_back: Number of hours back from now to fetch logs (alternative to start_time).
    :param filter_pattern: Optional filter pattern for log messages (e.g., "ERROR").
    :param log_stream_names: Optional list of log stream names to filter by.
    :return: A JSON string containing the list of log events or an error message.
    """
    try:
        # Determine start_time and end_time
        if start_time is not None and end_time is not None:
            # Use provided absolute times
            pass
        elif hours_back is not None:
            # Calculate relative time range
            now = int(datetime.now(timezone.utc).timestamp() * 1000)
            end_time = now
            start_time = end_time - (hours_back * 60 * 60 * 1000)
        else:
            # Default to last 24 hours
            hours_back = 24
            now = int(datetime.now(timezone.utc).timestamp() * 1000)
            end_time = now
            start_time = end_time - (hours_back * 60 * 60 * 1000)
        
        # Initialize list for all logs
        all_logs = []
        next_token = None
        
        # Loop to handle pagination
        while True:
            kwargs = {
                'logGroupName': log_group_name,
                'startTime': start_time,
                'endTime': end_time,
                'filterPattern': filter_pattern,
                # 'logStreamNames': log_stream_names
            }
            if next_token:
                kwargs['nextToken'] = next_token
            response = client.filter_log_events(**kwargs)
            all_logs.extend(response.get('events', []))
            if 'nextToken' in response:
                next_token = response['nextToken']
            else:
                break
        
        # Return logs as JSON
        return json.dumps(all_logs)
    
    except Exception as e:
        # Return error as JSON
        return json.dumps({"error": str(e)})


@aws_mcp.tool()
def create_cloudwatch_alarm(metric_name: str, threshold: float) -> str:
    """Create a CloudWatch alarm for the specified metric"""
    response = cloudwatch_client.put_metric_alarm(
        AlarmName=f"{metric_name}_alarm",
        ComparisonOperator='GreaterThanThreshold',
        EvaluationPeriods=1,
        MetricName=metric_name,
        Namespace='AWS/EC2',
        Period=300,
        Statistic='Average',
        Threshold=threshold,
        ActionsEnabled=False
    )
    return f"Created alarm for {metric_name} with threshold {threshold}"

