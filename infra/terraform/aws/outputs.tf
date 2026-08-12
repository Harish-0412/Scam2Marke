output "cluster_name" { value = aws_eks_cluster.main.name }
output "cluster_endpoint" {
  value     = aws_eks_cluster.main.endpoint
  sensitive = true
}
output "redis_primary_endpoint" {
  value = aws_elasticache_replication_group.redis.primary_endpoint_address
}
output "kafka_tls_bootstrap_brokers" { value = aws_msk_cluster.events.bootstrap_brokers_tls }
output "backup_bucket" { value = aws_s3_bucket.backups.id }
output "backup_kms_key_arn" { value = aws_kms_key.platform.arn }
output "tls_certificate_arn" { value = aws_acm_certificate_validation.api.certificate_arn }
output "workload_role_arn" { value = aws_iam_role.workload.arn }
