terraform {
  required_version = ">= 1.2.0"
  required_providers {
    oci = {
      source  = "oracle/oci"
      version = ">= 5.0.0"
    }
    null = {
      source = "hashicorp/null"
    }
  }
}

provider "oci" {
  tenancy_ocid = var.tenancy_ocid
  region       = var.region
}

# ───── 기존 컴퓨트 인스턴스 조회 (private_ip 획득) ─────
# 이 스택은 VM 을 새로 만들지 않는다. 이미 앱이 app_port 에서 도는
# 기존 인스턴스를 OCID 로 지정하면, 그 사설 IP 를 LB 백엔드로 연결한다.
data "oci_core_instance" "existing" {
  instance_id = var.instance_ocid
}

locals {
  lb_subnet  = var.subnet_id
  backend_ip = data.oci_core_instance.existing.private_ip
}

# ───── 기존 VM 에 소스 설치 (SSH remote-exec) ─────
# 부팅이 끝난 기존 인스턴스에는 cloud-init 을 못 쓰므로, SSH 로 접속해
# 설치 스크립트(install.sh.tftpl = cloud-init 과 동일 로직)를 실행한다.
# 재실행 트리거: instance/repo/branch/app_port 가 바뀌면 다시 설치한다.
resource "null_resource" "install" {
  triggers = {
    instance    = var.instance_ocid
    repo_url    = var.repo_url
    repo_branch = var.repo_branch
    app_port    = var.app_port
  }

  connection {
    type        = "ssh"
    host        = data.oci_core_instance.existing.public_ip
    user        = var.ssh_user
    private_key = var.ssh_private_key
    timeout     = "5m"
  }

  # 설치 스크립트 업로드 (opc 홈의 /tmp)
  provisioner "file" {
    content = templatefile("${path.module}/install.sh.tftpl", {
      repo_url    = var.repo_url
      repo_branch = var.repo_branch
      app_port    = var.app_port
    })
    destination = "/tmp/select-ai-install.sh"
  }

  # root 권한(sudo)으로 실행 → 패키지 설치/systemd 등록
  provisioner "remote-exec" {
    inline = [
      "chmod +x /tmp/select-ai-install.sh",
      "sudo bash /tmp/select-ai-install.sh",
    ]
  }
}

# ───── HTTPS Load Balancer (TLS 종단 → 기존 인스턴스 :app_port) ─────
resource "oci_load_balancer_load_balancer" "lb" {
  compartment_id = var.compartment_ocid
  display_name   = var.lb_display_name
  shape          = "flexible"
  shape_details {
    minimum_bandwidth_in_mbps = var.lb_min_bandwidth_mbps
    maximum_bandwidth_in_mbps = var.lb_max_bandwidth_mbps
  }
  subnet_ids = [local.lb_subnet]
  is_private = var.lb_is_private
}

resource "oci_load_balancer_backend_set" "bes" {
  load_balancer_id = oci_load_balancer_load_balancer.lb.id
  name             = "app-backendset"
  policy           = "ROUND_ROBIN"
  health_checker {
    protocol    = "HTTP"
    port        = var.app_port
    url_path    = "/"
    return_code = 200
  }
}

resource "oci_load_balancer_backend" "be" {
  load_balancer_id = oci_load_balancer_load_balancer.lb.id
  backendset_name  = oci_load_balancer_backend_set.bes.name
  ip_address       = local.backend_ip # 기존 인스턴스의 사설 IP
  port             = var.app_port
  depends_on       = [null_resource.install] # 앱 설치 후 백엔드 연결
}

# HTTPS 리스너 — OCI Certificates 서비스 인증서를 OCID 로 참조 (TLS 종단)
resource "oci_load_balancer_listener" "https" {
  load_balancer_id         = oci_load_balancer_load_balancer.lb.id
  name                     = "https"
  default_backend_set_name = oci_load_balancer_backend_set.bes.name
  port                     = var.https_port
  protocol                 = "HTTP" # OCI LB: HTTP + ssl_configuration = HTTPS 종단
  ssl_configuration {
    certificate_ids         = [var.certificate_ocid]
    verify_peer_certificate = false
  }
}

# (선택) 80 → 443 리다이렉트
resource "oci_load_balancer_rule_set" "redirect" {
  count            = var.enable_http_redirect ? 1 : 0
  load_balancer_id = oci_load_balancer_load_balancer.lb.id
  name             = "httptohttps"
  items {
    action        = "REDIRECT"
    response_code = 301
    conditions {
      attribute_name  = "PATH"
      attribute_value = "/"
      operator        = "FORCE_LONGEST_PREFIX_MATCH"
    }
    redirect_uri {
      protocol = "HTTPS"
      host     = "{host}"
      port     = var.https_port
      path     = "/{path}"
      query    = "?{query}"
    }
  }
}

resource "oci_load_balancer_listener" "http_redirect" {
  count                    = var.enable_http_redirect ? 1 : 0
  load_balancer_id         = oci_load_balancer_load_balancer.lb.id
  name                     = "http"
  default_backend_set_name = oci_load_balancer_backend_set.bes.name
  port                     = 80
  protocol                 = "HTTP"
  rule_set_names           = [oci_load_balancer_rule_set.redirect[0].name]
}
