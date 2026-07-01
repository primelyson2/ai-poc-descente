# OCI Resource Manager 변수.
# tenancy_ocid / compartment_ocid / region 은 Resource Manager 가 자동 주입한다
# (schema.yaml 에서 tenancy/region 은 숨김 처리).
#
# 이 변형(https-existing-vm)은 컴퓨트 인스턴스를 생성하지 않고,
# 기존 인스턴스(instance_ocid) 앞에 HTTPS Load Balancer 만 생성한다.
# → 컴퓨트/이미지/SSH/애플리케이션 소스 변수는 없다.

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

# ───── 대상 인스턴스 (기존 VM) ─────
variable "instance_ocid" {
  type        = string
  description = "소스를 설치하고 HTTPS LB 백엔드로 연결할 기존 컴퓨트 인스턴스 OCID"
}

# ───── 애플리케이션 설치 (기존 VM 에 SSH remote-exec) ─────
variable "ssh_private_key" {
  type        = string
  description = "기존 인스턴스에 SSH 접속할 개인키(PEM 전체 내용). 소스 설치용 — 공인 IP + 22 인바운드 필요"
  sensitive   = true
}

variable "ssh_user" {
  type        = string
  description = "SSH 접속 사용자 (Oracle Linux 기본 opc)"
  default     = "opc"
}

variable "repo_url" {
  type        = string
  description = "기존 VM 에 설치할 애플리케이션 Git 리포지토리 URL"
  default     = "https://github.com/primelyson2/select-ai-test.git"
}

variable "repo_branch" {
  type        = string
  description = "체크아웃할 브랜치"
  default     = "main"
}

# ───── Network (기존 VCN/서브넷 선택) ─────
variable "vcn_id" {
  type        = string
  description = "사용할 기존 가상 클라우드 네트워크(VCN) OCID"
}

variable "subnet_id" {
  type        = string
  description = "LB 를 배치할 기존 서브넷 OCID"
}

variable "app_port" {
  type        = number
  description = "기존 VM 의 애플리케이션 포트 (LB 백엔드/헬스체크 대상). LB→VM 인바운드 허용 필요"
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

variable "lb_display_name" {
  type        = string
  description = "Load Balancer 표시 이름"
  default     = "select-ai-test-lb"
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
