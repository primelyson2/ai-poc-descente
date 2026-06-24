locals {
  access_ip = var.assign_public_ip && oci_core_instance.app.public_ip != "" ? oci_core_instance.app.public_ip : oci_core_instance.app.private_ip
}

output "app_url" {
  description = "애플리케이션 접속 URL (HTTP, 인스턴스 직접)"
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
