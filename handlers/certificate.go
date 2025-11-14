package handlers

import (
	"crypto/sha256"
	"crypto/x509"
	"encoding/hex"
	"encoding/json"
	"encoding/pem"
	"fmt"
	"net/http"
	"time"

	"github.com/Ashmeet-21/Ash/models"
	"github.com/Ashmeet-21/Ash/storage"
	"github.com/gorilla/mux"
)

// CertificateHandler handles certificate-related HTTP requests
type CertificateHandler struct {
	storage *storage.MemoryStorage
}

// NewCertificateHandler creates a new certificate handler
func NewCertificateHandler(store *storage.MemoryStorage) *CertificateHandler {
	return &CertificateHandler{
		storage: store,
	}
}

// UploadCertificate handles POST requests to upload a certificate
func (h *CertificateHandler) UploadCertificate(w http.ResponseWriter, r *http.Request) {
	var req models.UploadRequest

	// Decode the JSON request body
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		respondWithError(w, http.StatusBadRequest, "Invalid request payload")
		return
	}

	// Parse the PEM encoded certificate
	block, _ := pem.Decode([]byte(req.Certificate))
	if block == nil {
		respondWithError(w, http.StatusBadRequest, "Failed to parse PEM block")
		return
	}

	// Parse the certificate
	cert, err := x509.ParseCertificate(block.Bytes)
	if err != nil {
		respondWithError(w, http.StatusBadRequest, fmt.Sprintf("Failed to parse certificate: %v", err))
		return
	}

	// Generate a unique ID for the certificate (using SHA-256 of the certificate)
	hash := sha256.Sum256(cert.Raw)
	certID := hex.EncodeToString(hash[:])

	// Extract key usage information
	keyUsage := extractKeyUsage(cert)

	// Convert IP addresses to strings
	ipAddresses := make([]string, len(cert.IPAddresses))
	for i, ip := range cert.IPAddresses {
		ipAddresses[i] = ip.String()
	}

	// Create certificate info
	certInfo := &models.CertificateInfo{
		ID:             certID,
		Subject:        cert.Subject.String(),
		Issuer:         cert.Issuer.String(),
		SerialNumber:   cert.SerialNumber.String(),
		NotBefore:      cert.NotBefore,
		NotAfter:       cert.NotAfter,
		SignatureAlgo:  cert.SignatureAlgorithm.String(),
		PublicKeyAlgo:  cert.PublicKeyAlgorithm.String(),
		KeyUsage:       keyUsage,
		IsCA:           cert.IsCA,
		Version:        cert.Version,
		DNSNames:       cert.DNSNames,
		EmailAddresses: cert.EmailAddresses,
		IPAddresses:    ipAddresses,
		UploadedAt:     time.Now(),
	}

	// Store the certificate
	if err := h.storage.Store(certInfo); err != nil {
		respondWithError(w, http.StatusInternalServerError, "Failed to store certificate")
		return
	}

	respondWithJSON(w, http.StatusCreated, certInfo)
}

// GetCertificate handles GET requests to retrieve a certificate by ID
func (h *CertificateHandler) GetCertificate(w http.ResponseWriter, r *http.Request) {
	vars := mux.Vars(r)
	certID := vars["id"]

	cert, err := h.storage.Get(certID)
	if err != nil {
		if err == storage.ErrCertificateNotFound {
			respondWithError(w, http.StatusNotFound, "Certificate not found")
			return
		}
		respondWithError(w, http.StatusInternalServerError, "Failed to retrieve certificate")
		return
	}

	respondWithJSON(w, http.StatusOK, cert)
}

// ListCertificates handles GET requests to list all certificates
func (h *CertificateHandler) ListCertificates(w http.ResponseWriter, r *http.Request) {
	certs, err := h.storage.List()
	if err != nil {
		respondWithError(w, http.StatusInternalServerError, "Failed to retrieve certificates")
		return
	}

	respondWithJSON(w, http.StatusOK, certs)
}

// DeleteCertificate handles DELETE requests to remove a certificate
func (h *CertificateHandler) DeleteCertificate(w http.ResponseWriter, r *http.Request) {
	vars := mux.Vars(r)
	certID := vars["id"]

	if err := h.storage.Delete(certID); err != nil {
		if err == storage.ErrCertificateNotFound {
			respondWithError(w, http.StatusNotFound, "Certificate not found")
			return
		}
		respondWithError(w, http.StatusInternalServerError, "Failed to delete certificate")
		return
	}

	respondWithJSON(w, http.StatusOK, map[string]string{"message": "Certificate deleted successfully"})
}

// extractKeyUsage converts x509.KeyUsage to a slice of strings
func extractKeyUsage(cert *x509.Certificate) []string {
	var usage []string

	if cert.KeyUsage&x509.KeyUsageDigitalSignature != 0 {
		usage = append(usage, "DigitalSignature")
	}
	if cert.KeyUsage&x509.KeyUsageContentCommitment != 0 {
		usage = append(usage, "ContentCommitment")
	}
	if cert.KeyUsage&x509.KeyUsageKeyEncipherment != 0 {
		usage = append(usage, "KeyEncipherment")
	}
	if cert.KeyUsage&x509.KeyUsageDataEncipherment != 0 {
		usage = append(usage, "DataEncipherment")
	}
	if cert.KeyUsage&x509.KeyUsageKeyAgreement != 0 {
		usage = append(usage, "KeyAgreement")
	}
	if cert.KeyUsage&x509.KeyUsageCertSign != 0 {
		usage = append(usage, "CertSign")
	}
	if cert.KeyUsage&x509.KeyUsageCRLSign != 0 {
		usage = append(usage, "CRLSign")
	}
	if cert.KeyUsage&x509.KeyUsageEncipherOnly != 0 {
		usage = append(usage, "EncipherOnly")
	}
	if cert.KeyUsage&x509.KeyUsageDecipherOnly != 0 {
		usage = append(usage, "DecipherOnly")
	}

	// Add extended key usage
	for _, ext := range cert.ExtKeyUsage {
		switch ext {
		case x509.ExtKeyUsageAny:
			usage = append(usage, "Any")
		case x509.ExtKeyUsageServerAuth:
			usage = append(usage, "ServerAuth")
		case x509.ExtKeyUsageClientAuth:
			usage = append(usage, "ClientAuth")
		case x509.ExtKeyUsageCodeSigning:
			usage = append(usage, "CodeSigning")
		case x509.ExtKeyUsageEmailProtection:
			usage = append(usage, "EmailProtection")
		case x509.ExtKeyUsageIPSECEndSystem:
			usage = append(usage, "IPSECEndSystem")
		case x509.ExtKeyUsageIPSECTunnel:
			usage = append(usage, "IPSECTunnel")
		case x509.ExtKeyUsageIPSECUser:
			usage = append(usage, "IPSECUser")
		case x509.ExtKeyUsageTimeStamping:
			usage = append(usage, "TimeStamping")
		case x509.ExtKeyUsageOCSPSigning:
			usage = append(usage, "OCSPSigning")
		}
	}

	return usage
}

// respondWithError sends an error response
func respondWithError(w http.ResponseWriter, code int, message string) {
	respondWithJSON(w, code, map[string]string{"error": message})
}

// respondWithJSON sends a JSON response
func respondWithJSON(w http.ResponseWriter, code int, payload interface{}) {
	response, err := json.Marshal(payload)
	if err != nil {
		w.WriteHeader(http.StatusInternalServerError)
		w.Write([]byte(`{"error":"Internal server error"}`))
		return
	}

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	w.Write(response)
}
