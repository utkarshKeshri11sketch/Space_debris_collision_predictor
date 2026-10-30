"""AWS Lambda entrypoint (API Gateway / Function URL). Handler: lambda_handler.handler

Note: API Gateway REST buffers responses, so SSE only streams incrementally via a Lambda Function URL
with RESPONSE_STREAM invoke mode; on buffered gateways the UI still works but events arrive at once.
"""
from mangum import Mangum

from app.main import app

handler = Mangum(app, lifespan="off")
