variable "aws_region" {
  type    = string
  default = "ap-south-1"
}
variable "environment" {
  type    = string
  default = "production"
}
variable "name" {
  type    = string
  default = "scam2market"
}
variable "vpc_cidr" {
  type    = string
  default = "10.42.0.0/16"
}
variable "domain_name" { type = string }
variable "route53_zone_id" { type = string }
variable "kubernetes_version" {
  type    = string
  default = "1.33"
}
variable "node_instance_types" {
  type    = list(string)
  default = ["m7i.large"]
}
variable "node_min_size" {
  type    = number
  default = 3
}
variable "node_max_size" {
  type    = number
  default = 12
}
variable "node_desired_size" {
  type    = number
  default = 3
}
variable "redis_node_type" {
  type    = string
  default = "cache.r7g.large"
}
variable "msk_instance_type" {
  type    = string
  default = "kafka.m7g.large"
}
variable "msk_broker_count" {
  type    = number
  default = 3
}
variable "backup_retention_days" {
  type    = number
  default = 35
}
variable "backup_database_secret_arn" {
  type        = string
  description = "Secrets Manager ARN containing BACKUP_DATABASE_URL for managed TimescaleDB."
}
