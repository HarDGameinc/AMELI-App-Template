from __future__ import annotations

from django import forms
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm

from .models import User

MAX_AVATAR_BYTES = 3 * 1024 * 1024


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
        fields = ["display_name", "theme_preference"]
        widgets = {
            "display_name": forms.TextInput(
                attrs={
                    "class": "modal-input",
                    "maxlength": 80,
                    "placeholder": "Alias visible (opcional)",
                    "autocomplete": "nickname",
                }
            ),
            "theme_preference": forms.Select(attrs={"class": "modal-input"}),
        }
        labels = {
            "display_name": "Alias visible",
            "theme_preference": "Tema preferido",
        }


class AvatarUploadForm(forms.Form):
    avatar = forms.ImageField(label="Imagen de perfil")

    def clean_avatar(self):
        avatar = self.cleaned_data["avatar"]
        if avatar.size > MAX_AVATAR_BYTES:
            raise forms.ValidationError("La imagen no puede superar 3 MB.")
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
