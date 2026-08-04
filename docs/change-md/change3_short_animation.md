# Atlas — Source-to-Video Pipeline · Change Spec v1

**Status:** The original scope and end-to-end pipeline works as intended, now is adding a new scope for the pipeline to be able to cover short animation, motion graphics and more of a visualizer video instead of a narration
**Prime directive:** Create a new director layer that is optimized specially for short animation, motion graphics and a visualizer video not a narration video

---

# Additional:

So the new scope intends our pipeline to be able to create a very short animation video, a range of 10-15s, the purpose of the video is not to explain materials, but is intended to help visualize the text being presented on the screen. The way I see it is that this pipeline can be very simple, as it does not need any sort of focused, narration, special character. So in my mind the pipeline that I though about is this

User sends "illustration" as blueprint_type -> new director layer optimized for this special task -> can either reuse the previous veo layer exposed through /pipeline/scenes -> probably reuse the old render layer but just for stitching

The new director blueprint should look like this
{
style: <string>,
style_type: <string>,

}

The

As you can see, the config layer's blueprint_type should accept an additional value which is "illustration", this "illustration" value is what will trigger this new director layer, and blueprint_type of "opening" and "summary" will still trigger the old director layer and pipeline.

So this new pipeline is fairly simple, there is no need for character or audio selection, there is no need to create storyboard, tts,
