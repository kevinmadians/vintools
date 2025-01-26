from flask import Flask, Response
import sys
import os
import json
from base64 import b64encode

# Add the root directory to Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from app import app

def handler(event, context):
    """Netlify function handler to process requests"""
    
    # Get HTTP method and path from the event
    http_method = event['httpMethod']
    path = event['path']
    
    # Get request body for POST requests
    body = event.get('body', '')
    if body and isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError:
            pass
    
    # Prepare headers
    headers = event.get('headers', {})
    if headers is None:
        headers = {}
    
    # Prepare the environment for Flask
    environ = {
        'REQUEST_METHOD': http_method,
        'PATH_INFO': path,
        'QUERY_STRING': event.get('queryStringParameters', {}),
        'CONTENT_LENGTH': str(len(str(body)) if body else '0'),
        'CONTENT_TYPE': headers.get('content-type', 'application/json'),
        'HTTP': 'on',
        'wsgi.version': (1, 0),
        'wsgi.input': body,
        'wsgi.errors': sys.stderr,
        'wsgi.multithread': False,
        'wsgi.multiprocess': False,
        'wsgi.run_once': False,
        'wsgi.url_scheme': 'https',
        'SERVER_NAME': headers.get('host', 'localhost'),
        'SERVER_PORT': '443',
        'SERVER_PROTOCOL': 'HTTP/1.1',
    }
    
    # Add headers to environ
    for header, value in headers.items():
        key = 'HTTP_' + header.upper().replace('-', '_')
        environ[key] = value
    
    # Handle the request through Flask
    response = app(environ)
    
    # Get response data
    response_data = response.get_data()
    
    # Handle binary responses (like JSON)
    try:
        response_data = response_data.decode('utf-8')
    except (UnicodeDecodeError, AttributeError):
        response_data = b64encode(response_data).decode('utf-8')
    
    # Prepare response headers
    response_headers = dict(response.headers)
    
    # Ensure content type is set for JSON responses
    if 'Content-Type' not in response_headers and path.endswith('/scrape'):
        response_headers['Content-Type'] = 'application/json'
    
    return {
        'statusCode': response.status_code,
        'headers': response_headers,
        'body': response_data,
        'isBase64Encoded': isinstance(response_data, bytes)
    } 