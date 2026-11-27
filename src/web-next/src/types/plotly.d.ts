declare module 'plotly.js-dist-min' {
  const Plotly: {
    newPlot(root: HTMLElement, data: object[], layout?: object, config?: object): Promise<HTMLElement>;
    react(root: HTMLElement, data: object[], layout?: object, config?: object): Promise<HTMLElement>;
    purge(root: HTMLElement): void;
    relayout(root: HTMLElement, update: object): Promise<HTMLElement>;
    restyle(root: HTMLElement, update: object, traces?: number[]): Promise<HTMLElement>;
    downloadImage(root: HTMLElement, opts: object): Promise<string>;
  };
  export default Plotly;
}
