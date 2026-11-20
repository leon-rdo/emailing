// Service worker da extensão: o carteiro entre o webmail e a tela do Emailing.
//
// Ele não lê e-mail, não fala com o servidor do Emailing e não envia nada. O
// que faz:
//   - abre a janela de confirmação (a própria tela de redação do Emailing);
//   - guarda a "carga" — o rascunho lido do webmail — até a tela pedir;
//   - repassa os anexos, que ficam na aba do webmail e só viajam quando pedidos;
//   - avisa o webmail do desfecho (enviado, agendado, fechou sem enviar).
//
// O estado mora em `chrome.storage.session`: um service worker é descartado a
// qualquer momento, e variável global aqui não sobrevive a isso.
importScripts("config.js");

const WEBMAILS = [
	/^https:\/\/([a-z0-9-]+\.)*titan\.email$/i,
	/^https:\/\/mail\.hostinger\.com$/i,
];
const ID_ROTEIRO = "emailing-preencher";
const PREFIXO = "confirmacao:";

const chaveDa = (abaId) => PREFIXO + abaId;

async function guardada(abaId) {
	const chave = chaveDa(abaId);
	return (await chrome.storage.session.get(chave))[chave] || null;
}

// O script que preenche a tela só pode ser registrado depois que o usuário
// informa o endereço do Emailing e concede a permissão para ele.
async function sincronizarRoteiro() {
	const config = await EmailingConfig.ler();
	const registrados = await chrome.scripting.getRegisteredContentScripts({ ids: [ID_ROTEIRO] });
	const permitido = !!config && (await chrome.permissions.contains({ origins: [config.padrao] }));
	if (!permitido) {
		if (registrados.length) await chrome.scripting.unregisterContentScripts({ ids: [ID_ROTEIRO] });
		return false;
	}
	const roteiro = {
		id: ID_ROTEIRO,
		matches: [config.padrao],
		js: ["emailing/preencher.js"],
		css: ["emailing/preencher.css"],
		runAt: "document_idle",
		persistAcrossSessions: true,
	};
	if (registrados.length) await chrome.scripting.updateContentScripts([roteiro]);
	else await chrome.scripting.registerContentScripts([roteiro]);
	return true;
}

async function fecharAnteriores(abaWebmail, idCompositor) {
	const tudo = await chrome.storage.session.get(null);
	for (const [chave, valor] of Object.entries(tudo)) {
		if (!chave.startsWith(PREFIXO) || !valor || !valor.origem) continue;
		if (valor.origem.abaId !== abaWebmail || valor.origem.idCompositor !== idCompositor) continue;
		// Trocada por uma nova: o webmail não precisa ouvir que esta "fechou".
		await chrome.storage.session.remove(chave);
		await chrome.windows.remove(valor.janelaId).catch(() => {});
	}
}

function origemDe(remetente) {
	if (remetente.origin) return remetente.origin;
	try {
		return new URL(remetente.url).origin;
	} catch (_erro) {
		return "";
	}
}

// A aba que fala é uma janela de confirmação aberta por nós, e está no Emailing?
async function confirmacaoDe(remetente) {
	if (!remetente.tab) return null;
	const config = await EmailingConfig.ler();
	if (!config || origemDe(remetente) !== config.origem) return null;
	return guardada(remetente.tab.id);
}

const TRATADORES = {
	// Do webmail: abrir a confirmação com este rascunho.
	"abrir-confirmacao": async (mensagem, remetente) => {
		if (!remetente.tab || !WEBMAILS.some((padrao) => padrao.test(origemDe(remetente)))) {
			return { ok: false, erro: "origem-recusada" };
		}
		const config = await EmailingConfig.ler();
		if (!config) {
			chrome.runtime.openOptionsPage();
			return { ok: false, erro: "sem-configuracao" };
		}
		if (!(await sincronizarRoteiro())) {
			chrome.runtime.openOptionsPage();
			return { ok: false, erro: "sem-permissao" };
		}

		const carga = mensagem.carga || {};
		await fecharAnteriores(remetente.tab.id, carga.idCompositor);

		// Em branco primeiro: a carga tem de estar guardada antes de a tela do
		// Emailing carregar e perguntar por ela.
		const janela = await chrome.windows.create({
			url: "about:blank", type: "popup", width: 1280, height: 860, focused: true,
		});
		const aba = janela.tabs[0];
		await chrome.storage.session.set({
			[chaveDa(aba.id)]: {
				id: crypto.randomUUID(),
				carga,
				origem: { abaId: remetente.tab.id, idCompositor: carga.idCompositor },
				janelaId: janela.id,
				concluida: false,
			},
		});
		await chrome.tabs.update(aba.id, { url: config.url + "/" });
		return { ok: true };
	},

	// Da tela do Emailing: existe um rascunho esperando nesta aba?
	"carga-da-aba": async (_mensagem, remetente) => {
		const confirmacao = await confirmacaoDe(remetente);
		if (!confirmacao || confirmacao.concluida) return null;
		return { id: confirmacao.id, carga: confirmacao.carga };
	},

	// Da tela do Emailing: um pedaço de um anexo, que continua na aba do webmail.
	"pedir-anexo": async (mensagem, remetente) => {
		const confirmacao = await confirmacaoDe(remetente);
		if (!confirmacao) return { ok: false, erro: "sem-confirmacao" };
		try {
			return await chrome.tabs.sendMessage(confirmacao.origem.abaId, {
				tipo: "fornecer-anexo",
				idCompositor: confirmacao.origem.idCompositor,
				indice: mensagem.indice,
				inicio: mensagem.inicio,
			});
		} catch (_erro) {
			return { ok: false, erro: "webmail-fechado" };
		}
	},

	// Da tela do Emailing: o que aconteceu com a mensagem.
	"resultado": async (mensagem, remetente) => {
		const confirmacao = await confirmacaoDe(remetente);
		if (!confirmacao) return { ok: false };
		const saiu = mensagem.resultado === "enviado" || mensagem.resultado === "agendado";
		if (saiu) {
			confirmacao.concluida = true;
			await chrome.storage.session.set({ [chaveDa(remetente.tab.id)]: confirmacao });
		}
		await chrome.tabs.sendMessage(confirmacao.origem.abaId, {
			tipo: "concluido",
			idCompositor: confirmacao.origem.idCompositor,
			resultado: mensagem.resultado,
		}).catch(() => {});
		return { ok: true };
	},

	"fechar-janela": async (_mensagem, remetente) => {
		const confirmacao = await confirmacaoDe(remetente);
		if (confirmacao) await chrome.windows.remove(confirmacao.janelaId).catch(() => {});
		return { ok: true };
	},
};

chrome.runtime.onMessage.addListener((mensagem, remetente, responder) => {
	const tratador = TRATADORES[mensagem && mensagem.tipo];
	if (!tratador) return;
	Promise.resolve()
		.then(() => tratador(mensagem, remetente))
		.then(responder, (erro) => responder({ ok: false, erro: String((erro && erro.message) || erro) }));
	return true; // a resposta é assíncrona
});

chrome.tabs.onRemoved.addListener(async (abaId) => {
	const confirmacao = await guardada(abaId);
	if (!confirmacao) return;
	await chrome.storage.session.remove(chaveDa(abaId));
	if (confirmacao.concluida) return;
	chrome.tabs.sendMessage(confirmacao.origem.abaId, {
		tipo: "concluido",
		idCompositor: confirmacao.origem.idCompositor,
		resultado: "fechada",
	}).catch(() => {});
});

chrome.runtime.onInstalled.addListener((detalhes) => {
	sincronizarRoteiro();
	if (detalhes.reason === "install") chrome.runtime.openOptionsPage();
});
chrome.runtime.onStartup.addListener(sincronizarRoteiro);
chrome.storage.onChanged.addListener((mudancas, area) => {
	if (area === "local" && mudancas[EmailingConfig.CHAVE]) sincronizarRoteiro();
});
chrome.permissions.onAdded.addListener(sincronizarRoteiro);
chrome.permissions.onRemoved.addListener(sincronizarRoteiro);
chrome.action.onClicked.addListener(() => chrome.runtime.openOptionsPage());
