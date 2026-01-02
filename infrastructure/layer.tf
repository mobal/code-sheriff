resource "aws_s3_bucket" "requirements_lambda_layer_bucket" {
  bucket_prefix = "lambda-layers-${var.stage}"
}

resource "aws_s3_object" "requirements_lambda_layer" {
  bucket = aws_s3_bucket.requirements_lambda_layer_bucket.id
  key    = "lambda_layers/${local.app_name}-requirements/requirements.zip"
  source = "${path.module}/../dist/requirements.zip"
}


resource "aws_lambda_layer_version" "requirements_lambda_layer" {
  compatible_architectures = [var.architecture]
  compatible_runtimes      = ["python3.13"]
  depends_on               = [aws_s3_object.requirements_lambda_layer]
  layer_name               = "${local.app_name}-requirements"
  s3_bucket                = aws_s3_bucket.requirements_lambda_layer_bucket.id
  s3_key                   = aws_s3_object.requirements_lambda_layer.key
  skip_destroy             = true
}
