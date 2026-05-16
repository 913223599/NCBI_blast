declare module 'plotly.js-dist-min' {
  const Plotly: {
    newPlot(root: HTMLElement, data: any[], layout?: any, config?: any): Promise<any>;
    react(root: HTMLElement, data: any[], layout?: any, config?: any): Promise<any>;
    purge(root: HTMLElement): void;
    relayout(root: HTMLElement, update: any): Promise<any>;
    restyle(root: HTMLElement, update: any, traces?: number[]): Promise<any>;
    downloadImage(root: HTMLElement, opts: any): Promise<string>;
  };
  export default Plotly;
}
