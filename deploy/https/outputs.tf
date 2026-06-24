locals {
  access_ip = var.assign_public_ip && oci_core_instance.app.public_ip != "" ? oci_core_instance.app.public_ip : oci_core_instance.app.private_ip
  lb_ip     = oci_load_balancer_load_balancer.lb.ip_address_details[0].ip_address
}

output "https_url" {
  description = "HTTPS 접속 URL (Load Balancer)"
  value       = var.https_port == 443 ? "https://${local.lb_ip}" : "https://${local.lb_ip}:${var.https_port}"
}

output "load_balancer_ip" {
  description = "Load Balancer 공인/사설 IP"
  value       = local.lb_ip
}

output "app_url" {
  description = "인스턴스 직접 접속 URL (HTTP, 디버깅용)"
  value       = "http://${local.access_ip}:${var.app_port}"
}

output "public_ip" {
  description = "인스턴스 공인 IP (private 서브넷이면 비어 있음)"
  value       = oci_core_instance.app.public_ip
}

output "private_ip" {
  description = "인스턴스 사설 IP"
  value       = oci_core_instance.app.private_ip
}

output "ssh_command" {
  description = "SSH 접속 명령"
  value       = "ssh opc@${local.access_ip}"
}
