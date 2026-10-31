# =============================================================================
# Terraform Variables Configuration (Non-Secret Values)
# Sensitive values (google_client_secret, database_url) are set in HCP Terraform
# =============================================================================

project_name = "new-project"
aws_region   = "us-east-1"

# Frontend origins for CORS and OAuth redirects
app_urls = [
  "http://localhost:5173",
  "http://localhost:3000"
]

# Email Configuration
recipient_email = "kornatskyy.pn@ucu.edu.ua"
sender_email    = "kornatskyy.pn@ucu.edu.ua"
alert_email     = "kornatskyy.pn@ucu.edu.ua"

# AI Agenda Parser Configuration
parser_model    = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
allowed_origins = "*"

# Backend Networking & Database Container Image
image_uri         = "277206319329.dkr.ecr.us-east-1.amazonaws.com/new-project-backend:58ba331"
vpc_id            = "vpc-0235a3e4bea7b33ce"
subnet_ids        = ["subnet-0b258d3ecf26a53dc", "subnet-0805ca8b1437c10f3"]
security_group_id = "sg-064b04146ba303461"
route_table_id    = "rtb-0c2a0fbb7f56e744a"
