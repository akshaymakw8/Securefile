import os
import json
import boto3
from botocore.exceptions import ClientError
from datetime import datetime

s3 = boto3.client('s3')
BUCKET = os.environ.get('UPLOAD_BUCKET')
PASSWORD = os.environ.get('UPLOAD_PASSWORD')
REGION = os.environ.get('REGION', 'us-east-1')

def respond(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type",
            "Access-Control-Allow-Methods": "POST, OPTIONS"
        },
        "body": json.dumps(body)
    }

def lambda_handler(event, context):
    """
    Handle two types of requests:
    1. POST /generate-bulk-upload-urls - Generate presigned URLs for uploads
    2. S3 trigger - Extract text from uploaded PDFs
    """
    
    # Check if this is an S3 event trigger
    if 'Records' in event and event['Records'][0].get('eventSource') == 'aws:s3':
        return handle_s3_trigger(event)
    
    # Otherwise, handle API Gateway request
    return handle_api_request(event)

def handle_api_request(event):
    """Generate presigned URLs for file uploads"""
    try:
        # Parse request body
        body_raw = event.get('body', '{}')
        try:
            body = json.loads(body_raw)
        except Exception:
            return respond(400, {"error": "Invalid JSON body"})
        
        # Validate password
        if not PASSWORD:
            return respond(500, {"error": "Server misconfiguration: upload password not set"})
        
        if body.get('password') != PASSWORD:
            return respond(401, {"error": "Unauthorized"})
        
        # Get file list
        files = body.get('files', [])
        if not files or not isinstance(files, list):
            return respond(400, {"error": "files array is required"})
        
        # Generate presigned URLs for each file
        presigned_urls = []
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        for file_info in files:
            file_name = file_info.get('fileName')
            content_type = file_info.get('contentType', 'application/octet-stream')
            
            if not file_name:
                return respond(400, {"error": "fileName is required for each file"})
            
            # Create unique S3 key with timestamp
            s3_key = f"uploads/{timestamp}_{file_name}"
            
            try:
                # Generate presigned URL for PUT operation
                presigned_url = s3.generate_presigned_url(
                    'put_object',
                    Params={
                        'Bucket': BUCKET,
                        'Key': s3_key,
                        'ContentType': content_type
                    },
                    ExpiresIn=3600  # URL valid for 1 hour
                )
                
                presigned_urls.append({
                    'fileName': file_name,
                    'uploadURL': presigned_url,
                    's3Key': s3_key
                })
                
            except ClientError as e:
                return respond(500, {
                    "error": f"Failed to generate presigned URL for {file_name}",
                    "detail": str(e)
                })
        
        return respond(200, {
            "message": "Presigned URLs generated successfully",
            "presignedUrls": presigned_urls
        })
        
    except Exception as e:
        return respond(500, {"error": "Server error", "detail": str(e)})

def handle_s3_trigger(event):
    """Extract text from PDF files uploaded to S3"""
    try:
        import tempfile
        import PyPDF2
        
        for record in event['Records']:
            bucket = record['s3']['bucket']['name']
            key = record['s3']['object']['key']
            
            # Only process PDFs in the uploads/ folder
            if not key.lower().endswith('.pdf') or not key.startswith('uploads/'):
                continue
            
            print(f"Processing PDF: {key}")
            
            # Download PDF from S3
            with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp_file:
                try:
                    s3.download_file(bucket, key, tmp_file.name)
                    
                    # Extract text
                    extracted_text = extract_text_from_pdf(tmp_file.name)
                    
                    if extracted_text and extracted_text.strip():
                        # Create extracted text key
                        file_name = os.path.basename(key)
                        base_name = os.path.splitext(file_name)[0]
                        extracted_key = f"extracted/{base_name}.txt"
                        
                        # Upload extracted text
                        s3.put_object(
                            Bucket=bucket,
                            Key=extracted_key,
                            Body=extracted_text.encode('utf-8'),
                            ContentType='text/plain'
                        )
                        
                        print(f"Extracted text saved to: {extracted_key}")
                    else:
                        print(f"No text extracted from {key}")
                        
                except Exception as e:
                    print(f"Error processing {key}: {str(e)}")
                finally:
                    # Clean up temp file
                    if os.path.exists(tmp_file.name):
                        os.remove(tmp_file.name)
        
        return {"statusCode": 200, "body": "Processing complete"}
        
    except Exception as e:
        print(f"S3 trigger error: {str(e)}")
        return {"statusCode": 500, "body": str(e)}

def extract_text_from_pdf(path):
    """Extract text from PDF file"""
    text_parts = []
    with open(path, 'rb') as f:
        reader = PyPDF2.PdfReader(f)
        for page in reader.pages:
            try:
                page_text = page.extract_text() or ""
            except Exception:
                page_text = ""
            if page_text:
                text_parts.append(page_text)
    return "\n\n".join(text_parts)
