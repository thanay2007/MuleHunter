/**
 * Chrome strings, English and Hindi.
 *
 * SCOPE IS DELIBERATE AND NARROW: masthead, classification strip, navigation,
 * breadcrumbs, footer, case-header field labels, and the freeze-order document.
 * The operations canvas, the analytics and every explanatory sentence stay in
 * English.
 *
 * Half-translated body copy looks worse than none -- it reads as a machine
 * translation somebody abandoned, and it undermines the one thing the frame is
 * there to do. Field labels and institutional furniture are exactly the part
 * that a bilingual government surface really does carry, so that is the part
 * that is here.
 *
 * Devanagari renders in IBM Plex Sans, which the app already ships.
 */

export type Language = 'en' | 'hi'

export interface ChromeStrings {
  /** Masthead lockup. */
  centreName: string
  consoleName: string

  classification: string

  navActiveIncident: string
  navNetworkAnalysis: string
  navBenchmark: string
  navProvenance: string
  navOrders: string
  navAudit: string

  crumbHome: string
  crumbIncidents: string
  crumbPlan: string

  /** Case header field labels. */
  caseId: string
  complaintRef: string
  amountReported: string
  reportingBank: string
  victimDistrict: string
  status: string

  statusAwaiting: string
  statusUnderInterdiction: string
  statusExecuted: string

  /** Golden-hour meter. */
  windowRemaining: string
  windowClosed: string
  complaintFiled: string

  /** Officer chip. */
  officerDesk: string

  /** Footer and the standing disclaimer. */
  disclaimer: string
  build: string
  seed: string
  deterministic: string
  auditId: string

  /** Freeze order document. */
  orderTitle: string
  orderIssuedBy: string
  orderCountersigned: string
  orderJustification: string
  orderInstruction: string
  orderAccount: string
  orderAction: string
  orderIssueAt: string
  orderExpectedRecovery: string
  orderRequiresSecondApproval: string
}

const en: ChromeStrings = {
  centreName: 'Cyber Financial Fraud Mitigation Centre',
  consoleName: 'Inter-Bank Interdiction Console · Prototype',

  classification:
    'RESTRICTED — FOR AUTHORISED USE ONLY · SYNTHETIC DATA · PROTOTYPE',

  navActiveIncident: 'Active Incident',
  navNetworkAnalysis: 'Network Analysis',
  navBenchmark: 'Benchmark & Assurance',
  navProvenance: 'Data Provenance',
  navOrders: 'Freeze Orders',
  navAudit: 'Audit Trail',

  crumbHome: 'Home',
  crumbIncidents: 'Active Incidents',
  crumbPlan: 'Interdiction Plan',

  caseId: 'CASE ID',
  complaintRef: 'COMPLAINT REF',
  amountReported: 'AMOUNT REPORTED',
  reportingBank: 'REPORTING BANK',
  victimDistrict: 'VICTIM DISTRICT',
  status: 'STATUS',

  statusAwaiting: 'AWAITING REPORT',
  statusUnderInterdiction: 'UNDER INTERDICTION',
  statusExecuted: 'PLAN EXECUTED',

  windowRemaining: 'of recoverable window remaining',
  windowClosed: 'recoverable window closed',
  complaintFiled: 'complaint filed',

  officerDesk: 'Interdiction Desk',

  disclaimer:
    'Prototype system. Not affiliated with, endorsed by, or connected to the ' +
    'Reserve Bank of India, I4C, or any bank. All data synthetic.',
  build: 'Build',
  seed: 'Seed',
  deterministic: 'Deterministic',
  auditId: 'Audit ID',

  orderTitle: 'FREEZE INSTRUCTION — IMMEDIATE',
  orderIssuedBy: 'Issued by',
  orderCountersigned: 'Countersigned by',
  orderJustification: 'Justification',
  orderInstruction: 'Instruction',
  orderAccount: 'Account',
  orderAction: 'Action',
  orderIssueAt: 'Issue at',
  orderExpectedRecovery: 'Expected recovery',
  orderRequiresSecondApproval: 'REQUIRES SECOND APPROVAL',
}

const hi: ChromeStrings = {
  centreName: 'साइबर वित्तीय धोखाधड़ी शमन केंद्र',
  consoleName: 'अंतर-बैंक अवरोधन कंसोल · प्रोटोटाइप',

  classification:
    'प्रतिबंधित — केवल अधिकृत उपयोग हेतु · कृत्रिम डेटा · प्रोटोटाइप',

  navActiveIncident: 'सक्रिय घटना',
  navNetworkAnalysis: 'नेटवर्क विश्लेषण',
  navBenchmark: 'मानक एवं आश्वासन',
  navProvenance: 'डेटा स्रोत',
  navOrders: 'फ्रीज़ आदेश',
  navAudit: 'अंकेक्षण अभिलेख',

  crumbHome: 'मुख्य पृष्ठ',
  crumbIncidents: 'सक्रिय घटनाएँ',
  crumbPlan: 'अवरोधन योजना',

  caseId: 'प्रकरण संख्या',
  complaintRef: 'शिकायत संदर्भ',
  amountReported: 'सूचित राशि',
  reportingBank: 'सूचक बैंक',
  victimDistrict: 'पीड़ित का जिला',
  status: 'स्थिति',

  statusAwaiting: 'रिपोर्ट प्रतीक्षित',
  statusUnderInterdiction: 'अवरोधन जारी',
  statusExecuted: 'योजना निष्पादित',

  windowRemaining: 'वसूली अवधि शेष',
  windowClosed: 'वसूली अवधि समाप्त',
  complaintFiled: 'शिकायत दर्ज',

  officerDesk: 'अवरोधन डेस्क',

  disclaimer:
    'प्रोटोटाइप प्रणाली। भारतीय रिज़र्व बैंक, I4C अथवा किसी बैंक से संबद्ध, ' +
    'अनुमोदित या संबंधित नहीं। समस्त डेटा कृत्रिम है।',
  build: 'बिल्ड',
  seed: 'सीड',
  deterministic: 'नियतात्मक',
  auditId: 'अंकेक्षण आईडी',

  orderTitle: 'फ्रीज़ निर्देश — तत्काल',
  orderIssuedBy: 'जारीकर्ता',
  orderCountersigned: 'प्रतिहस्ताक्षरकर्ता',
  orderJustification: 'औचित्य',
  orderInstruction: 'निर्देश',
  orderAccount: 'खाता',
  orderAction: 'कार्रवाई',
  orderIssueAt: 'जारी करने का समय',
  orderExpectedRecovery: 'अपेक्षित वसूली',
  orderRequiresSecondApproval: 'द्वितीय अनुमोदन आवश्यक',
}

export const STRINGS: Record<Language, ChromeStrings> = { en, hi }

/** The label shown on each side of the language toggle. */
export const LANGUAGE_LABEL: Record<Language, string> = { en: 'EN', hi: 'हिं' }
