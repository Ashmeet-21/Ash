package models

import "time"

// CertificateInfo holds the parsed details of a certificate
type CertificateInfo struct {
	ID             string    `json:"id"`
	Subject        string    `json:"subject"`
	Issuer         string    `json:"issuer"`
	SerialNumber   string    `json:"serial_number"`
	NotBefore      time.Time `json:"not_before"`
	NotAfter       time.Time `json:"not_after"`
	SignatureAlgo  string    `json:"signature_algorithm"`
	PublicKeyAlgo  string    `json:"public_key_algorithm"`
	KeyUsage       []string  `json:"key_usage"`
	IsCA           bool      `json:"is_ca"`
	Version        int       `json:"version"`
	DNSNames       []string  `json:"dns_names,omitempty"`
	EmailAddresses []string  `json:"email_addresses,omitempty"`
	IPAddresses    []string  `json:"ip_addresses,omitempty"`
	UploadedAt     time.Time `json:"uploaded_at"`
}

// UploadRequest represents the request body for uploading a certificate
type UploadRequest struct {
	Certificate string `json:"certificate"` // PEM encoded certificate
}
