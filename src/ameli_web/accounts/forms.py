from __future__ import annotations

from django import forms
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm

from .models import User

MAX_AVATAR_BYTES = 3 * 1024 * 1024


class TemplateAuthenticationForm(AuthenticationForm):
    username = forms.CharField(label="Usuario")
    password = forms.CharField(label="Contraseña", strip=False, widget=forms.PasswordInput)


class ProfilePreferencesForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["display_name", "theme_preference"]
        widgets = {
            "display_name": forms.TextInput(attrs={"maxlength": 80, "placeholder": "Alias visible (opcional)"}),
            "theme_preference": forms.Select(),
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
    old_password = forms.CharField(label="Contraseña actual", strip=False, widget=forms.PasswordInput)
    new_password1 = forms.CharField(label="Nueva contraseña", strip=False, widget=forms.PasswordInput)
    new_password2 = forms.CharField(label="Repite la nueva contraseña", strip=False, widget=forms.PasswordInput)
