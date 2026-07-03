locals {
  lb_ip = oci_load_balancer_load_balancer.lb.ip_address_details[0].ip_address
}

output "https_url" {
  description = "HTTPS 접속 URL (Load Balancer)"
  value       = var.https_port == 443 ? "https://${local.lb_ip}" : "https://${local.lb_ip}:${var.https_port}"
}

output "load_balancer_ip" {
  description = "Load Balancer 공인/사설 IP"
  value       = local.lb_ip
}

output "backend_ip" {
  description = "LB 백엔드로 연결된 기존 인스턴스 사설 IP (확인용)"
  value       = local.backend_ip
}
