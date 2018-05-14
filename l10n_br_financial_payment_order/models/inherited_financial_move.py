# -*- coding: utf-8 -*-
# Copyright 2017 KMEE INFORMATICA LTDA
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from __future__ import division, print_function, unicode_literals

import datetime

from openerp import api, fields, models, _

from pybrasil.febraban import (valida_codigo_barras, valida_linha_digitavel,
    identifica_codigo_barras, monta_linha_digitavel, monta_codigo_barras,
    formata_linha_digitavel)
from pybrasil.inscricao import limpa_formatacao
from pybrasil.valor import formata_valor

from ..febraban.boleto.document import BoletoOdoo

import logging
_logger = logging.getLogger(__name__)


class FinancialMove(models.Model):
    _inherit = b'financial.move'

    #
    # Integração bancária via CNAB
    #
    payment_mode_id = fields.Many2one(
        comodel_name='payment.mode',
        string='Carteira de cobrança',
        ondelete='restrict',
    )
    tipo_pagamento = fields.Selection(
        related='payment_mode_id.tipo_pagamento',
        store=True,
    )
    boleto_carteira = fields.Char(
        related='payment_mode_id.boleto_carteira',
        store=True,
    )
    tipo_documento = fields.Char(
        related='document_type_id.name',
        store=True,
    )
    #
    # Implementa o nosso número como NUMERIC no Postgres, pois alguns
    # bancos têm números bem grandes, que não dão certo com integers
    #
    nosso_numero = fields.Float(
        string='Nosso número',
        digits=(21, 0),
    )
    #
    # Para pagamentos automatizados de boletos de terceiros
    #
    boleto_linha_digitavel = fields.Char(
        string='Linha digitável',
        size=55,
    )
    boleto_codigo_barras = fields.Char(
        string='Código de barras',
        size=44,
    )

    #
    # Informações do Boleto para contribuição sindical
    #
    sindicato_qtd_contribuintes = fields.Integer(
        string='Quantidade Total de Contribuintes',
    )

    sindicato_total_remuneracao_contribuintes = fields.Float(
        string='Total Remuneração dos contribuintes',
    )

    sindicato_total_empregados = fields.Integer(
        string='Quantidade Total de empregados estabelecimentos'
    )

    cod_receita = fields.Char(
        string='Código da receita da DARF',
    )

    valor_inss_terceiros = fields.Char(
        string='Valor do INSS de terceiros',
    )
    valor_inss = fields.Char(
        string='Valor do INSS',
    )

    descricao = fields.Char(
        string='Descrição da Movimentação financeira',
    )

    def _trata_linha_digitavel(self):
        self.ensure_one()

        if not self.boleto_linha_digitavel:
            return

        #
        # Foi informado o número via leitura do codigo de barras?
        #
        if valida_codigo_barras(self.boleto_linha_digitavel):
            codigo_barras = self.boleto_linha_digitavel
            linha_digitavel = monta_linha_digitavel(codigo_barras)
        #
        # Ou foi informado via digitação mesmo?
        #
        elif valida_linha_digitavel(self.boleto_linha_digitavel):
            codigo_barras = monta_codigo_barras(self.boleto_linha_digitavel)
            linha_digitavel = \
                formata_linha_digitavel(self.boleto_linha_digitavel)

        else:
            return
            #raise código inválido

        identificacao = identifica_codigo_barras(codigo_barras)

        if identificacao is None:
            return
            #raise código inválido

        self.boleto_linha_digitavel = linha_digitavel
        self.boleto_codigo_barras = codigo_barras

        if 'valor' in identificacao:
            self.amount_document = identificacao['valor']

        if 'vencimento' in identificacao and \
                identificacao['vencimento'] is not None:
            self.date_maturity = str(identificacao['vencimento'])

    @api.multi
    @api.onchange('boleto_linha_digitavel')
    def _onchange_linha_digitavel(self):
        for move in self:
            move._trata_linha_digitavel()

    @api.multi
    @api.depends('boleto_linha_digitavel')
    def _depends_linha_digitavel(self):
        for move in self:
            move._trata_linha_digitavel()

    @api.multi
    def button_boleto(self):
        for financial_move in self:
            # Guia DARF
            if financial_move.document_type_id.name == 'DARF':
                action = self.env['report'].get_action(
                    self, b'l10n_br_financial_payment_order.py3o_darf'
                )
            # Guia GPS
            elif financial_move.document_type_id.name == 'GPS':
                action = self.env['report'].get_action(
                    self, b'l10n_br_financial_payment_order.py3o_gps'
                )
            # Boleto do Sindicato
            elif financial_move.payment_mode_id.boleto_carteira == 'SIND':
                action = self.env['report'].get_action(
                    self,
                    b'l10n_br_financial_payment_order.py3o_boleto_sindicato'
                )
            # Boleto generico
            else:
                action = self.env['report'].get_action(
                    self,
                    b'l10n_br_financial_payment_order.py3o_boleto_generico'
                )
        return action

    @api.multi
    def gera_boleto(self):
        boleto_list = []

        for financial_move in self:
            # try:
            if True:
                #
                # Para a carteira da guia sindical, o nosso número é sempre
                # os 12 primeiros dígitos do CNPJ da empresa
                #
                if financial_move.payment_mode_id.boleto_carteira == 'SIND':
                    nosso_numero = \
                        limpa_formatacao(financial_move.company_id.cnpj_cpf)
                    nosso_numero = nosso_numero[:12]
                else:
                    if financial_move.nosso_numero:
                        nosso_numero = financial_move.nosso_numero
                    else:
                        sequence_nosso_numero_id = \
                            financial_move.payment_mode_id.\
                                sequence_nosso_numero_id.id

                        nosso_numero = self.env['ir.sequence'].next_by_id(
                            sequence_nosso_numero_id
                        )
                        nosso_numero = str(nosso_numero)

                boleto = BoletoOdoo(financial_move, nosso_numero)

                if financial_move.payment_mode_id.boleto_carteira == 'SIND':
                    boleto.boleto.cnae = \
                        financial_move.company_id.cnae_main_id.code
                    codigo_sindical = \
                        financial_move.payment_mode_id.beneficiario_codigo
                    codigo_sindical += \
                        financial_move.payment_mode_id.beneficiario_digito
                    boleto.boleto.codigo_sindical = codigo_sindical

                    # Informações boleto para sindicato
                    boleto.boleto.total_empregados = \
                        financial_move.sindicato_total_empregados
                    boleto.boleto.qtd_contribuintes = \
                        financial_move.sindicato_qtd_contribuintes
                    boleto.boleto.total_remuneracao_contribuintes = \
                        financial_move.sindicato_total_remuneracao_contribuintes

                if boleto:
                #     financial_move.date_payment_created = date.today()
                #     financial_move.transaction_ref = \
                #         boleto.boleto.format_nosso_numero()
                    financial_move.nosso_numero = nosso_numero

                boleto_list.append(boleto.boleto)

            # except BoletoException as be:
            #     _logger.error(be.message or be.value, exc_info=True)
            #     continue
            #
            # except Exception as e:
            #     _logger.error(e.message or e.value, exc_info=True)
            #     continue

        return boleto_list

    def last_day_of_month(self, any_day):
        next_month = any_day.replace(day=28) + datetime.timedelta(days=4)
        next_month -= datetime.timedelta(days=next_month.day)
        return next_month.day

    @api.multi
    def gera_pdf_darf(self):
        """
        Função que implementa o relatório py3o da DARF
        :return:
        """
        class DarfObj(object):
            def __init__(self, dados_darf):
                self.legal_name = dados_darf['legal_name']
                self.telefone = dados_darf['telefone']
                self.cnpj = dados_darf['cnpj']
                self.periodo_apuracao = dados_darf['periodo_apuracao']
                self.cod_receita = dados_darf['cod_receita']
                # self.num_referencia = dados_darf['num_referencia']
                self.vencimento = dados_darf['vencimento']
                self.valor_principal = dados_darf['valor_principal']
                self.valor_multa = dados_darf['valor_multa']
                self.valor_juros_encargos = dados_darf['valor_juros_encargos']
                self.valor_total = dados_darf['valor_total']

        dados_darf = {}
        for financial_move in self:
            mes = financial_move.doc_source_id.mes
            ano = financial_move.doc_source_id.ano
            ultimo_dia_mes = self.last_day_of_month(
                datetime.date(int(ano), int(mes), 1))
            periodo_apuracao = str(ultimo_dia_mes) + '/' + str(mes) + '/' + \
                str(ano)
            dados_darf['legal_name'] = financial_move.partner_id.legal_name
            dados_darf['telefone'] = financial_move.partner_id.phone
            dados_darf['cnpj'] = financial_move.partner_id.cnpj_cpf
            dados_darf['periodo_apuracao'] = periodo_apuracao
            dados_darf['cod_receita'] = financial_move.cod_receita
            # dados_darf['num_referencia'] =
            data_vencimento = \
                fields.Date.from_string(financial_move.date_maturity)
            dia = '0' + str(data_vencimento.day) if data_vencimento.day < \
                10 else data_vencimento.day
            mes = '0' + str(data_vencimento.month) if data_vencimento.month < \
                10 else data_vencimento.month
            dados_darf['vencimento'] = \
                str(dia) + '/' + str(mes) + '/' + str(data_vencimento.year)
            valor_principal = financial_move.amount_document
            valor_multa = 0.00
            valor_juros_encargos = 0.00
            valor_total = valor_principal + valor_multa + valor_juros_encargos
            dados_darf['valor_principal'] = formata_valor(valor_principal)
            dados_darf['valor_multa'] = '0,00'
            dados_darf['valor_juros_encargos'] = '0,00'
            dados_darf['valor_total'] = formata_valor(valor_total)
        return DarfObj(dados_darf)

    @api.multi
    def gera_pdf_gps(self):
        class GpsObj(object):
            def __init__(self, dados_gps):
                self.legal_name = dados_gps['legal_name']
                self.telefone = dados_gps['telefone']
                self.cnpj = dados_gps['cnpj']
                self.endereco = dados_gps['endereco']
                self.numero = dados_gps['numero']
                self.bairro = dados_gps['bairro']
                self.cidade = dados_gps['cidade']
                self.estado = dados_gps['estado']
                self.cep = dados_gps['cep']
                self.competencia = dados_gps['competencia']
                self.vencimento = dados_gps['vencimento']
                self.valor_inss = dados_gps['valor_inss']
                self.valor_outras_entidades = \
                    dados_gps['valor_outras_entidades']
                self.valor_total = dados_gps['valor_total']

        dados_gps = {}
        for financial_move in self:
            dados_gps['legal_name'] = financial_move.company_id.legal_name
            dados_gps['telefone'] = financial_move.company_id.phone
            dados_gps['cnpj'] = financial_move.company_id.cnpj_cpf
            dados_gps['endereco'] = financial_move.company_id.street
            dados_gps['numero'] = financial_move.company_id.number
            dados_gps['bairro'] = financial_move.company_id.district
            dados_gps['cidade'] = financial_move.company_id.l10n_br_city_id.name
            dados_gps['estado'] = financial_move.company_id.state_id.name
            dados_gps['cep'] = financial_move.company_id.zip
            dados_gps['competencia'] = financial_move.doc_source_id.mes + \
                '/' + financial_move.doc_source_id.ano
            data_vencimento = \
                fields.Date.from_string(financial_move.date_maturity)
            dia = '0' + str(data_vencimento.day) if data_vencimento.day < \
                10 else data_vencimento.day
            mes = '0' + str(data_vencimento.month) if data_vencimento.month < \
                10 else data_vencimento.month
            dados_gps['vencimento'] = \
                str(dia) + '/' + str(mes) + '/' + str(data_vencimento.year)
            dados_gps['valor_inss'] = \
                formata_valor(float(financial_move.valor_inss))
            dados_gps['valor_outras_entidades'] = \
                formata_valor(float(financial_move.valor_inss_terceiros))
            dados_gps['valor_total'] = \
                formata_valor(financial_move.amount_document)

        return GpsObj(dados_gps)
