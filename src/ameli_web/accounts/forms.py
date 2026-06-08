from __future__ import annotations

from django import forms
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm

from .models import User

MAX_AVATAR_BYTES = 3 * 1024 * 1024
MAX_AVATAR_DIMENSION = 4096  # pixels per side; refuses decompression bombs
ALLOWED_AVATAR_FORMATS = {"JPEG", "PNG", "WEBP", "GIF"}


class TemplateAuthenticationForm(AuthenticationForm):
    username = forms.CharField(label="Usuario")
    password = forms.CharField(
        label="Contrasena",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
    )


class ProfilePreferencesForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["display_name", "email", "theme_preference"]
        widgets = {
            "display_name": forms.TextInput(
                attrs={
                    "class": "modal-input",
                    "maxlength": 80,
                    "placeholder": "Alias visible (opcional)",
                    "autocomplete": "nickname",
                }
            ),
            "email": forms.EmailInput(
                attrs={
                    "class": "modal-input",
                    "maxlength": 254,
                    "placeholder": "tu@dominio.com",
                    "autocomplete": "email",
                }
            ),
            "theme_preference": forms.Select(attrs={"class": "modal-input"}),
        }
        labels = {
            "display_name": "Alias visible",
            "email": "Email",
            "theme_preference": "Tema preferido",
        }

    def clean_email(self):
        return (self.cleaned_data.get("email") or "").strip().lower()


class AvatarUploadForm(forms.Form):
    avatar = forms.ImageField(label="Imagen de perfil")

    def clean_avatar(self):
        """Validate avatar upload beyond what ``ImageField`` does on its own.

        ``ImageField`` already runs the file through Pillow to confirm it
        decodes as an image, which closes most polyglot-file vectors. On
        top of that we enforce:

        - a byte ceiling (cheap DoS via giant uploads)
        - a format whitelist (rules out SVG with embedded JS that some
          Pillow plugins do accept, plus exotic raster formats)
        - a pixel ceiling (defeats decompression bombs — a 50 000 px
          PNG can pass the byte check but blow up RAM on display)
        """
        from PIL import Image, UnidentifiedImageError

        avatar = self.cleaned_data["avatar"]
        if avatar.size > MAX_AVATAR_BYTES:
            raise forms.ValidationError("La imagen no puede superar 3 MB.")
        try:
            avatar.file.seek(0)
            with Image.open(avatar.file) as img:
                fmt = (img.format or "").upper()
                if fmt not in ALLOWED_AVATAR_FORMATS:
                    raise forms.ValidationError(
                        f"Formato no soportado ({fmt or 'desconocido'}). "
                        "Usa JPEG, PNG, WebP o GIF."
                    )
                width, height = img.size
                if width > MAX_AVATAR_DIMENSION or height > MAX_AVATAR_DIMENSION:
                    raise forms.ValidationError(
                        f"La imagen es muy grande ({width}x{height}). "
                        f"Maximo {MAX_AVATAR_DIMENSION} px por lado."
                    )
        except UnidentifiedImageError as exc:
            raise forms.ValidationError("No se pudo identificar la imagen.") from exc
        finally:
            try:
                avatar.file.seek(0)
            except Exception:  # pragma: no cover - some upload streams aren't seekable
                pass
        return avatar


class ProfilePasswordForm(PasswordChangeForm):
    old_password = forms.CharField(
        label="Contrasena actual",
        strip=False,
        widget=forms.PasswordInput(
            attrs={
                "class": "modal-input",
                "autocomplete": "current-password",
                "placeholder": "Tu clave actual",
            }
        ),
    )
    new_password1 = forms.CharField(
        label="Nueva contrasena",
        strip=False,
        widget=forms.PasswordInput(
            attrs={
                "class": "modal-input",
                "autocomplete": "new-password",
                "placeholder": "Minimo 12 caracteres",
            }
        ),
    )
    new_password2 = forms.CharField(
        label="Repite la nueva contrasena",
        strip=False,
        widget=forms.PasswordInput(
            attrs={
                "class": "modal-input",
                "autocomplete": "new-password",
                "placeholder": "Repite la nueva contrasena",
            }
        ),
    )
