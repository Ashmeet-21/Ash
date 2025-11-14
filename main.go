package main

import (
	"fmt"
	"log"
	"net/http"
	"os"

	"github.com/Ashmeet-21/Ash/handlers"
	"github.com/Ashmeet-21/Ash/storage"
	"github.com/gorilla/mux"
)

func main() {
	// Get port from environment or use default
	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}

	// Initialize storage
	store := storage.NewMemoryStorage()

	// Initialize handlers
	certHandler := handlers.NewCertificateHandler(store)

	// Set up router
	router := mux.NewRouter()

	// API routes
	api := router.PathPrefix("/api/v1").Subrouter()

	// Certificate routes
	api.HandleFunc("/certificates", certHandler.UploadCertificate).Methods("POST")
	api.HandleFunc("/certificates", certHandler.ListCertificates).Methods("GET")
	api.HandleFunc("/certificates/{id}", certHandler.GetCertificate).Methods("GET")
	api.HandleFunc("/certificates/{id}", certHandler.DeleteCertificate).Methods("DELETE")

	// Health check endpoint
	router.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		w.Write([]byte(`{"status":"healthy"}`))
	}).Methods("GET")

	// Log all routes
	log.Println("Starting Certificate API Server...")
	log.Printf("Server listening on port %s", port)
	log.Println("\nAvailable endpoints:")
	log.Println("  POST   /api/v1/certificates       - Upload a certificate")
	log.Println("  GET    /api/v1/certificates       - List all certificates")
	log.Println("  GET    /api/v1/certificates/{id}  - Get certificate details")
	log.Println("  DELETE /api/v1/certificates/{id}  - Delete a certificate")
	log.Println("  GET    /health                    - Health check")

	// Start server
	addr := fmt.Sprintf(":%s", port)
	if err := http.ListenAndServe(addr, router); err != nil {
		log.Fatal("Server failed to start: ", err)
	}
}
