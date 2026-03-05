FROM public.ecr.aws/lambda/python:3.14

# Install dependencies
COPY cloud/requirements.txt ${LAMBDA_TASK_ROOT}/requirements.txt
RUN pip install --no-cache-dir -r ${LAMBDA_TASK_ROOT}/requirements.txt

# Copy shared source code
COPY src/ ${LAMBDA_TASK_ROOT}/src/

# Copy Lambda handlers
COPY cloud/__init__.py ${LAMBDA_TASK_ROOT}/cloud/__init__.py
COPY cloud/handlers.py ${LAMBDA_TASK_ROOT}/cloud/handlers.py

# Default handler (overridden per-function in SAM template)
CMD ["cloud.handlers.handle_receive"]
