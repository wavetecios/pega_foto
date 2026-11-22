from django import forms


class UploadFotoForm(forms.Form):
    imagem = forms.ImageField()
    codigo_evento = forms.CharField(max_length=50, required=False)

    def clean_codigo_evento(self):
        return self.cleaned_data["codigo_evento"] or "evento_padrao"
