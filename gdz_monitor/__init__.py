"""
GDZ Monitor — aplicação desktop (PyWebView) para o servidor Hero Saga.

Camadas:
    app/       ponte com a UI (janela PyWebView, API exposta ao JS, workers)
    web/       frontend HTML/CSS/JS carregado na janela
    services/  regras de negócio (mercado, MVP, loot, builds, alertas, drops)
    adapters/  acesso a sistemas externos (HTTP, scraping, sessão, disco)
    external/  integrações com serviços de terceiros (Divine Pride, ícones)
    core/      configurações, caminhos e constantes partilhadas
"""
