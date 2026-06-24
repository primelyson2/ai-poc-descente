# OCI Resource Manager 변수.
# tenancy_ocid / compartment_ocid / region 은 Resource Manager 가 자동 주입한다
# (schema.yaml 에서 tenancy/region 은 숨김 처리).

variable "tenancy_ocid" {
  type        = string
  description = "테넌시 OCID (Resource Manager 자동 주입)"
}

variable "compartment_ocid" {
  type        = string
  description = "리소스를 생성할 구획 OCID"
}

variable "region" {
  type        = string
  description = "리전 (Resource Manager 자동 주입)"
}

# ───── Compute ─────
variable "instance_display_name" {
  type        = string
  description = "컴퓨트 인스턴스 표시 이름"
  default     = "select-ai-test"
}

variable "availability_domain" {
  type        = string
  description = "가용 도메인 이름 (비우면 첫 번째 AD 사용)"
  default     = ""
}

variable "instance_shape" {
  type        = string
  description = "컴퓨트 shape"
  default     = "VM.Standard.E5.Flex"
}

variable "instance_ocpus" {
  type        = number
  description = "OCPU 수 (Flex shape 전용)"
  default     = 1
}

variable "instance_memory_gbs" {
  type        = number
  description = "메모리 GB (Flex shape 전용)"
  default     = 8
}

variable "os_version" {
  type        = string
  description = "Oracle Linux 버전"
  default     = "9"
}

variable "ssh_public_key" {
  type        = string
  description = "인스턴스 SSH 접속용 공개키 (선택 — 비우면 SSH 키 미등록)"
  default     = ""
}

# ───── Network (기존 VCN/서브넷 선택) ─────
variable "vcn_id" {
  type        = string
  description = "사용할 기존 가상 클라우드 네트워크(VCN) OCID"
}

variable "subnet_id" {
  type        = string
  description = "인스턴스 주 VNIC 가 생성될 기존 서브넷 OCID"
}

variable "assign_public_ip" {
  type        = bool
  description = "공인 IP 할당 여부 (public 서브넷이어야 함). private 서브넷이면 false"
  default     = true
}

variable "app_port" {
  type        = number
  description = "애플리케이션 포트 (선택한 서브넷의 보안 목록에서 인바운드 허용 필요)"
  default     = 8000
}

# ───── HTTPS (Load Balancer) ─────
variable "certificate_ocid" {
  type        = string
  description = "OCI Certificates 서비스의 인증서 OCID (LB 443 리스너가 참조)"
}

variable "https_port" {
  type        = number
  description = "HTTPS 리스너 포트"
  default     = 443
}

variable "lb_subnet_id" {
  type        = string
  description = "LB 배치 서브넷 OCID (비우면 인스턴스 subnet_id 재사용)"
  default     = ""
}

variable "lb_min_bandwidth_mbps" {
  type        = number
  description = "Flexible LB 최소 대역폭(Mbps)"
  default     = 10
}

variable "lb_max_bandwidth_mbps" {
  type        = number
  description = "Flexible LB 최대 대역폭(Mbps)"
  default     = 10
}

variable "lb_is_private" {
  type        = bool
  description = "LB 를 private 로 생성할지 여부 (기본 public)"
  default     = false
}

variable "enable_http_redirect" {
  type        = bool
  description = "80 포트 리스너로 HTTPS(443) 리다이렉트 추가"
  default     = true
}

# ───── Application source ─────
variable "repo_url" {
  type        = string
  description = "애플리케이션 Git 리포지토리 URL"
  default     = "https://github.com/primelyson2/select-ai-test.git"
}

variable "repo_branch" {
  type        = string
  description = "체크아웃할 브랜치"
  default     = "main"
}
