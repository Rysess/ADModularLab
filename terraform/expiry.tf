# Terminates (default) or stops the lab when its ExpiresAt tag passes. Runs in
# AWS rather than a local cron, which would not fire with the operator's machine
# off. Set lab.expires_action: stop to keep the disks and just halt compute.

locals {
  expires_enabled = try(local.lab.expires_enabled, true)
  expires_action  = try(local.lab.expires_action, "terminate")
  expiry_count    = local.expires_enabled ? 1 : 0
}

data "archive_file" "expire" {
  count       = local.expiry_count
  type        = "zip"
  source_file = "${path.module}/lambda/expire.py"
  output_path = "${path.module}/expire.zip"
}

data "aws_iam_policy_document" "expire_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "expire" {
  statement {
    actions   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["arn:aws:logs:*:*:*"]
  }

  # DescribeInstances cannot be scoped to a resource or conditioned on tags.
  statement {
    actions   = ["ec2:DescribeInstances"]
    resources = ["*"]
  }

  statement {
    actions   = ["ec2:StopInstances", "ec2:TerminateInstances"]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/Lab"
      values   = [local.lab.name]
    }
  }
}

resource "aws_iam_role" "expire" {
  count              = local.expiry_count
  name               = "${local.lab.name}-expire"
  assume_role_policy = data.aws_iam_policy_document.expire_assume.json
  tags               = local.lab_tags
}

resource "aws_iam_role_policy" "expire" {
  count  = local.expiry_count
  name   = "${local.lab.name}-expire"
  role   = aws_iam_role.expire[0].id
  policy = data.aws_iam_policy_document.expire.json
}

resource "aws_cloudwatch_log_group" "expire" {
  count             = local.expiry_count
  name              = "/aws/lambda/${local.lab.name}-expire"
  retention_in_days = 7
  tags              = local.lab_tags
}

resource "aws_lambda_function" "expire" {
  count            = local.expiry_count
  function_name    = "${local.lab.name}-expire"
  role             = aws_iam_role.expire[0].arn
  filename         = data.archive_file.expire[0].output_path
  source_code_hash = data.archive_file.expire[0].output_base64sha256
  handler          = "expire.handler"
  runtime          = "python3.12"
  timeout          = 60
  tags             = local.lab_tags

  environment {
    variables = {
      LAB_NAME      = local.lab.name
      EXPIRE_ACTION = local.expires_action
    }
  }

  depends_on = [aws_cloudwatch_log_group.expire]
}

resource "aws_cloudwatch_event_rule" "expire" {
  count               = local.expiry_count
  name                = "${local.lab.name}-expire"
  schedule_expression = "rate(1 hour)"
  tags                = local.lab_tags
}

resource "aws_cloudwatch_event_target" "expire" {
  count     = local.expiry_count
  rule      = aws_cloudwatch_event_rule.expire[0].name
  target_id = "lambda"
  arn       = aws_lambda_function.expire[0].arn
}

resource "aws_lambda_permission" "expire" {
  count         = local.expiry_count
  statement_id  = "AllowEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.expire[0].function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.expire[0].arn
}
