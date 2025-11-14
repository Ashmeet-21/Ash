package storage

import (
	"errors"
	"sync"

	"github.com/Ashmeet-21/Ash/models"
)

var (
	// ErrCertificateNotFound is returned when a certificate is not found
	ErrCertificateNotFound = errors.New("certificate not found")
)

// MemoryStorage provides in-memory storage for certificates
type MemoryStorage struct {
	mu           sync.RWMutex
	certificates map[string]*models.CertificateInfo
}

// NewMemoryStorage creates a new in-memory storage
func NewMemoryStorage() *MemoryStorage {
	return &MemoryStorage{
		certificates: make(map[string]*models.CertificateInfo),
	}
}

// Store saves a certificate to storage
func (s *MemoryStorage) Store(cert *models.CertificateInfo) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	s.certificates[cert.ID] = cert
	return nil
}

// Get retrieves a certificate by ID
func (s *MemoryStorage) Get(id string) (*models.CertificateInfo, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()

	cert, exists := s.certificates[id]
	if !exists {
		return nil, ErrCertificateNotFound
	}

	return cert, nil
}

// List returns all stored certificates
func (s *MemoryStorage) List() ([]*models.CertificateInfo, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()

	certs := make([]*models.CertificateInfo, 0, len(s.certificates))
	for _, cert := range s.certificates {
		certs = append(certs, cert)
	}

	return certs, nil
}

// Delete removes a certificate from storage
func (s *MemoryStorage) Delete(id string) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	if _, exists := s.certificates[id]; !exists {
		return ErrCertificateNotFound
	}

	delete(s.certificates, id)
	return nil
}
