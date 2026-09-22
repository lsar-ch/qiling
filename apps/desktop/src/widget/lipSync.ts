/** 口型同步总线：语音播放链路写入 AnalyserNode，VrmStage 渲染循环读取 RMS。 */
export const lipSyncBus: { analyser: AnalyserNode | null } = { analyser: null };
