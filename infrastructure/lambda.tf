resource "aws_lambda_function" "fastapi" {
  function_name = "${local.app_name}-fastapi"
  role          = aws_iam_role.lambda_role.arn
  runtime       = "python3.13"
  handler       = "app.api_handler.handler"

  filename         = "${path.module}/../dist/api.zip"
  source_code_hash = filebase64sha256("${path.module}/../dist/api.zip")

  architectures = [var.architecture]
  timeout       = 120
  memory_size   = 768

  layers = [
    aws_lambda_layer_version.requirements_lambda_layer.arn,
    "arn:aws:lambda:${var.aws_region}:017000801446:layer:AWSLambdaPowertoolsPythonV3-python313-${var.architecture}:18"
  ]

  environment {
    variables = {
      APP_NAME                             = var.app_name
      DEBUG                                = var.debug
      LOG_LEVEL                            = var.log_level
      POWERTOOLS_LOGGER_LOG_EVENT          = "true"
      POWERTOOLS_SERVICE_NAME              = var.power_tools_service_name
      POWERTOOLS_DEBUG                     = "false"
      RATE_LIMIT_DURATION_IN_SECONDS       = var.rate_limit_duration_in_seconds
      RATE_LIMIT_REQUESTS                  = var.rate_limit_requests
      RATE_LIMITING                        = var.rate_limiting
      STAGE                                = var.stage

      ANTHROPIC_API_KEY                    = var.anthropic_api_key
      GITHUB_TOKEN                         = var.github_token
      GITHUB_WEBHOOK_SECRET                = var.github_webhook_secret
    }
  }
  depends_on = [
    aws_iam_role_policy_attachment.lambda_policy_attachment,
    aws_lambda_layer_version.requirements_lambda_layer,
  ]
}
