import resend
import os

sender = os.getenv("EMAIL_FROM")

def enviar_email_reset(destinatario, link_reset):
    try:
        email = resend.Emails.send({
            "from": sender,
            "to": destinatario,
            "subject": "Reset de senha",
            "html": f"""
                <table width='100%' cellpadding='0' cellspacing='0' style='background:#f5f6fa; padding:30px 0; font-family:Arial, Helvetica, sans-serif;'>
                  <tr>
                    <td align='center'>

                      <table width='480' cellpadding='0' cellspacing='0' style='background:white; border-radius:12px; padding:30px; box-shadow:0 2px 8px rgba(0,0,0,0.08);'>

                        <tr>
                          <td align='center' style='padding-bottom:20px;'>
                            <h2 style='margin:0; color:#2c3e50; font-size:26px;'>Redefinição de Senha</h2>
                          </td>
                        </tr>

                        <tr>
                          <td style='color:#444; font-size:15px; line-height:22px;'>
                            <p>Olá, {sender}</p>

                            <p>Recebemos uma solicitação para redefinir sua senha.<br>
                            Para continuar, clique no botão abaixo:</p>
                          </td>
                        </tr>

                        <tr>
                          <td align='center' style='padding:22px 0;'>
                            <a href='{link_reset}'
                               style='background:#4CAF50; color:white; padding:14px 28px; text-decoration:none; 
                                      border-radius:8px; font-weight:bold; display:inline-block; font-size:16px;'>
                                Redefinir Senha
                            </a>
                          </td>
                        </tr>

                        <tr>
                          <td style='color:#555; font-size:14px; line-height:20px;'>
                            <p>Se você não solicitou esta alteração, basta ignorar este e-mail.</p>
                            <p>Por segurança, este link expira em <strong>30 minutos</strong>.</p>
                          </td>
                        </tr>

                        <tr>
                          <td align='center' style='padding-top:25px; font-size:12px; color:#999;'>
                            <hr style='border:none; border-top:1px solid #eee; margin-bottom:18px;'>
                            © 2025 — Sistema de Cadastro Facial  
                          </td>
                        </tr>

                      </table>

                    </td>
                  </tr>
                </table>
            """
        })

        return True
    except Exception as e:
        print(f"Erro ao enviar email: {e}")
        return False
