# Optional Cloud TTS output is a real managed capability, not a URI-shaped placeholder. The
# bucket is regional, CMEK-bound and inaccessible through object ACLs. Text remains the record
# of authority; these objects are a derived accessibility artifact with lifecycle expiry.
resource "google_storage_bucket" "voice_briefs" {
  project                     = var.project_id
  name                        = "${var.project_id}-${local.render_catalog_id}-voice"
  location                    = local.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false

  encryption {
    default_kms_key_name = google_kms_crypto_key.cmek.id
  }

  lifecycle_rule {
    condition {
      age = 30
    }
    action {
      type = "Delete"
    }
  }

  depends_on = [
    google_project_service.required,
    google_kms_crypto_key_iam_member.storage,
  ]
}

resource "google_storage_bucket_iam_member" "voice_writer" {
  bucket = google_storage_bucket.voice_briefs.name
  role   = "roles/storage.objectCreator"
  member = "serviceAccount:${google_service_account.app.email}"
}
