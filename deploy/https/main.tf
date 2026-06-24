terraform {
  required_version = ">= 1.2.0"
  required_providers {
    oci = {
      source  = "oracle/oci"
      version = ">= 5.0.0"
    }
  }
}

provider "oci" {
  tenancy_ocid = var.tenancy_ocid
  region       = var.region
}

# ───── 가용 도메인 / 이미지 조회 ─────
data "oci_identity_availability_domains" "ads" {
  compartment_id = var.tenancy_ocid
}

data "oci_core_images" "ol" {
  compartment_id           = var.compartment_ocid
  operating_system         = "Oracle Linux"
  operating_system_version = var.os_version
  shape                    = var.instance_shape
  sort_by                  = "TIMECREATED"
  sort_order               = "DESC"
}

locals {
  ad_name   = var.availability_domain != "" ? var.availability_domain : data.oci_identity_availability_domains.ads.availability_domains[0].name
  image_id  = data.oci_core_images.ol.images[0].id
  is_flex   = length(regexall("Flex", var.instance_shape)) > 0
  lb_subnet = var.lb_subnet_id != "" ? var.lb_subnet_id : var.subnet_id
}

# ───── 컴퓨트 인스턴스 (기존 VCN/서브넷 사용) ─────
resource "oci_core_instance" "app" {
  compartment_id      = var.compartment_ocid
  availability_domain = local.ad_name
  display_name        = var.instance_display_name
  shape               = var.instance_shape

  dynamic "shape_config" {
    for_each = local.is_flex ? [1] : []
    content {
      ocpus         = var.instance_ocpus
      memory_in_gbs = var.instance_memory_gbs
    }
  }

  create_vnic_details {
    subnet_id        = var.subnet_id
    assign_public_ip = var.assign_public_ip
    display_name     = "${var.instance_display_name}-vnic"
  }

  source_details {
    source_type = "image"
    source_id   = local.image_id
  }

  metadata = merge(
    {
      user_data = base64encode(templatefile("${path.module}/cloud-init.tftpl", {
        repo_url    = var.repo_url
        repo_branch = var.repo_branch
        app_port    = var.app_port
      }))
    },
    var.ssh_public_key != "" ? { ssh_authorized_keys = var.ssh_public_key } : {}
  )
}

# ───── HTTPS Load Balancer (TLS 종단 → 인스턴스 :app_port) ─────
resource "oci_load_balancer_load_balancer" "lb" {
  compartment_id = var.compartment_ocid
  display_name   = "${var.instance_display_name}-lb"
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
  ip_address       = oci_core_instance.app.private_ip # 암묵적 depends_on
  port             = var.app_port
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
