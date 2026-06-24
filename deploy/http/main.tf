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
  ad_name  = var.availability_domain != "" ? var.availability_domain : data.oci_identity_availability_domains.ads.availability_domains[0].name
  image_id = data.oci_core_images.ol.images[0].id
  is_flex  = length(regexall("Flex", var.instance_shape)) > 0
}

# ───── 컴퓨트 인스턴스 (기존 VCN/서브넷 사용) ─────
# HTTP 변형: Load Balancer/인증서 없이 인스턴스의 app_port 로 직접 접속한다.
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
